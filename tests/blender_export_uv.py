"""Native UV round trips, source preservation, deformation context and rollback."""
import json
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_export
from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_export_uv import promote

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder);bridge._workspace=root
    runpy.run_path(str(Path(__file__).with_name('export_uv_fixture.py')))
    hero,peer=[bpy.data.objects[n] for n in ['Hero','Peer']]
    original=hero.data
    def uv_signature(mesh,index):
        return sorted(tuple(round(float(c),5) for c in row.vector) for row in mesh.uv_layers[index].uv)
    atlas,shader=uv_signature(original,1),uv_signature(original,0)
    def snapshot():
        return {'ids':ids(),'mesh':hero.data,'peer_mesh':peer.data,
            'layers':[u.name for u in original.uv_layers],
            'coords':[uv_signature(original,i) for i in range(2)],
            'flags':[[[getattr(v,f) for v in u.data] for f in ['pin_uv']]
                     for u in original.uv_layers],
            'active':original.uv_layers.active_index,'render':[u.active_render for u in original.uv_layers],
            'slots':[(s.link,s.material) for s in hero.material_slots],
            'selection':set(bpy.context.selected_objects),'object':bpy.context.view_layer.objects.active,
            'frame':bpy.context.scene.frame_current,
            'key_values':[k.value for k in original.shape_keys.key_blocks]}
    def positions():
        bpy.context.view_layer.update()
        value=hero.evaluated_get(bpy.context.evaluated_depsgraph_get())
        return np.array([tuple(v.co) for v in value.data.vertices])
    before=snapshot()
    poses={}
    for frame in [1,3]:bpy.context.scene.frame_set(frame);poses[frame]=positions()
    bpy.context.scene.frame_set(1)
    with promote([hero],'Atlas') as rows:
        assert hero.data!=original and peer.data==original
        assert rows[0]['source_index']==1 and rows[0]['export_index']==0
        for frame in [1,3]:
            bpy.context.scene.frame_set(frame)
            assert np.max(abs(positions()-poses[frame]))<1e-6
    bpy.context.scene.frame_set(1)
    assert snapshot()==before
    state=bridge.dispatch('session_control',{'action':'inspect'})
    lease=bridge.dispatch('session_control',{'action':'claim','owner':'uv-native',
        'expected_project':state['project_id']})['lease_id']
    def edit(operation,**params):
        return bridge.dispatch('owned_edit',{'operation':operation,'params':{**params,'lease_id':lease}})
    results={}
    for extension in ['fbx','glb','usda']:
        result=edit('export_uv_asset',names=['Hero'],path='hero.'+extension,uv_layer='Atlas')
        assert result['uv_maps'][0]['layers']==(['st','ShaderUV'] if extension=='usda' else ['Atlas','ShaderUV'])
        assert snapshot()==before
        if extension=='fbx':
            from io_scene_fbx import parse_fbx
            document,_=parse_fbx.parse(str(root/'hero.fbx'))
            def elements(value):
                yield value
                for child in value.elems:yield from elements(child)
            layer=next(e for e in elements(document) if e.id==b'LayerElementTangent' and e.props[0]==0)
            tangent=next(e.props[0] for e in layer.elems if e.id==b'Tangents')
            assert tangent[0]>.9,tuple(tangent[:3])
        operation={ 'fbx':'import_fbx','glb':'import_mesh','usda':'import_usd'}[extension]
        imported=edit(operation,path='hero.'+extension,name='RoundTrip_'+extension)
        imported_names=[n['name'] if isinstance(n,dict) else n for n in imported['objects']]
        names=[n for n in imported_names if bpy.data.objects.get(n) and bpy.data.objects[n].type=='MESH']
        assert len(names)==1,imported
        data=bpy.data.objects[names[0]].data
        primary=list(data.uv_layers.keys()).index('st') if extension=='usda' else 0
        secondary=list(data.uv_layers.keys()).index('ShaderUV') if extension=='usda' else 1
        assert uv_signature(data,primary)==atlas,(extension,list(data.uv_layers.keys()),uv_signature(data,primary),atlas)
        assert uv_signature(data,secondary)==shader,(extension,uv_signature(data,secondary),shader)
        results[extension]={'primary_matches_atlas':True,'secondary_uv_preserved':True}
        for name in imported_names:
            obj=bpy.data.objects.get(name)
            if obj:
                mesh=obj.data if obj.type=='MESH' else None
                bpy.data.objects.remove(obj,do_unlink=True)
                if mesh and not mesh.users:bpy.data.meshes.remove(mesh)
        # Imported material IDs are independent of the export's restoration check.
        before=snapshot()
    original.uv_layers[0].name='st'
    before=snapshot()
    usd=edit('export_uv_asset',names=['Hero'],path='collision.usda',uv_layer='Atlas')
    assert usd['uv_maps'][0]['layers']==['st','Atlas']
    assert usd['uv_maps'][0]['export_index'] is None and usd['uv_maps'][0]['export_primvar']=='st'
    assert snapshot()==before
    imported=edit('import_usd',path='collision.usda',name='Collision')
    mesh=next(bpy.data.objects[row['name']].data for row in imported['objects']
              if bpy.data.objects[row['name']].type=='MESH')
    assert uv_signature(mesh,list(mesh.uv_layers.keys()).index('st'))==atlas
    assert uv_signature(mesh,list(mesh.uv_layers.keys()).index('Atlas'))==shader
    before=snapshot()
    with patch.object(blender_export,'fbx',side_effect=RuntimeError('encoder failure')):
        try:edit('export_uv_asset',names=['Hero'],path='failed.fbx',uv_layer='Atlas')
        except RuntimeError as exc:assert str(exc)=='encoder failure'
        else:raise AssertionError('Expected native encoder failure')
    assert not (root/'failed.fbx').exists() and snapshot()==before
    try:edit('export_uv_asset',names=['Hero'],path='missing.fbx',uv_layer='Missing')
    except ValueError:pass
    else:raise AssertionError('Missing UV layer was silently exported')
    assert not (root/'missing.fbx').exists() and snapshot()==before
    print(json.dumps({'native_uv_export':'passed','formats':results,
        'source_uvs_shared_mesh_bindings_and_flags_preserved':True,
        'morph_context_preserved':True,'usd_st_name_collision_handled':True,
        'fbx_uv0_tangent_basis_checked':True,'failed_export_removed_file_and_restored_state':True}))
