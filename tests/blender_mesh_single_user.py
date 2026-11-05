"""Native copying retains object identity and deformation and cleans failed copies."""
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_objects
from cavi_blender_mcp.blender_asset_library import ids

with tempfile.TemporaryDirectory() as folder:
    os.environ['CAVI_BLENDER_WORKSPACE'] = folder
    runpy.run_path(str(Path(__file__).with_name('mesh_single_user_fixture.py')))
    target, peer = bpy.data.objects['TileGrid'], bpy.data.objects['LinkedPeer']
    source = target.data
    def data(mesh):
        keys = mesh.shape_keys
        return {'vertices':[tuple(v.co) for v in mesh.vertices],
            'weights':[[(g.group,g.weight) for g in v.groups] for v in mesh.vertices],
            'faces':[(tuple(p.vertices),p.material_index) for p in mesh.polygons],
            'edges':[(tuple(e.vertices),e.use_seam) for e in mesh.edges],
            'uvs':[[tuple(v.uv) for v in u.data] for u in mesh.uv_layers],
            'active_uv':mesh.uv_layers.active_index, 'render_uv':[u.active_render for u in mesh.uv_layers],
            'hint':mesh['asset_hint'], 'materials':list(mesh.materials),
            'keys':[(k.name,k.value,k.relative_key.name,[tuple(v.co) for v in k.data]) for k in keys.key_blocks],
            'action':keys.animation_data.action, 'slot':keys.animation_data.action_slot,
            'drivers':[(d.data_path,d.driver.expression,
                [(v.name,v.targets[0].id,v.targets[0].data_path) for v in d.driver.variables])
                for d in keys.animation_data.drivers]}
    def context():
        return {'object':target.as_pointer(), 'world':[list(row) for row in target.matrix_world],
            'parent':target.parent, 'groups':[(g.name,g.index) for g in target.vertex_groups],
            'modifiers':[(m.name,m.type,m.object) for m in target.modifiers],
            'slots':[(s.link,s.material) for s in target.material_slots],
            'selected':set(bpy.context.selected_objects), 'active':bpy.context.view_layer.objects.active,
            'collections':list(target.users_collection), 'frame':bpy.context.scene.frame_current}
    def motion():
        result=[]
        frame=bpy.context.scene.frame_current
        try:
            for sample in [1,6,11]:
                bpy.context.scene.frame_set(sample)
                for value in [target,peer]:
                    evaluated=value.evaluated_get(bpy.context.evaluated_depsgraph_get())
                    mesh=evaluated.to_mesh()
                    try:
                        result.extend(tuple(evaluated.matrix_world@v.co) for v in mesh.vertices)
                    finally:
                        evaluated.to_mesh_clear()
        finally:
            bpy.context.scene.frame_set(frame)
        return result
    before_motion=motion()
    assert bridge.dispatch('scene_info', {'limit':1})['total'] > 0
    before_data, before_context, before_ids = data(source), context(), ids()
    state=bridge.dispatch('session_control',{'action':'inspect'})
    lease=bridge.dispatch('session_control',{'action':'claim','owner':'variant-author',
        'expected_project':state['project_id']})['lease_id']
    def copy():
        return bridge.dispatch('owned_edit',{'operation':'make_mesh_single_user',
            'params':{'name':target.name,'lease_id':lease}})
    with patch.object(blender_objects,'info',side_effect=RuntimeError('receipt failure')):
        try:
            copy()
        except RuntimeError as exc:
            assert str(exc)=='receipt failure'
        else:
            raise AssertionError('Expected a receipt failure after native copying')
    assert target.data == peer.data == source and ids()==before_ids
    assert data(source)==before_data and context()==before_context
    result=copy()
    clone=target.data
    assert result['mesh_copy']['copied'] and clone!=source and peer.data==source
    assert clone.shape_keys != source.shape_keys and clone.library is None
    assert clone.users==1 and not clone.use_fake_user and source.use_fake_user
    assert data(clone)==before_data and data(source)==before_data and context()==before_context
    after_motion=motion()
    error=max(abs(a-b) for left,right in zip(before_motion,after_motion,strict=True)
        for a,b in zip(left,right,strict=True))
    assert error<1e-6,error
    successful_ids=ids()
    assert not copy()['mesh_copy']['copied'] and target.data==clone and ids()==successful_ids
    uv_before=[tuple(v.uv) for v in source.uv_layers['UVMap'].data]
    bridge.dispatch('owned_edit',{'operation':'transform_uv','params':{'name':target.name,
        'uv_layer':'UVMap','transform':{'faces':[0],'offset':[-1,-1]},'lease_id':lease}})
    assert [tuple(v.uv) for v in source.uv_layers['UVMap'].data]==uv_before
    assert tuple(clone.uv_layers['UVMap'].data[0].uv)!=uv_before[0]
    library=Path(folder)/'source-library.blend'
    bpy.data.libraries.write(str(library),{source})
    with bpy.data.libraries.load(str(library),link=True) as (_available,loaded):
        loaded.meshes=[source.name]
    linked=loaded.meshes[0]
    local=bpy.data.objects.new('LinkedMeshData',linked)
    bpy.context.scene.collection.objects.link(local)
    identity=local.as_pointer()
    linked_result=bridge.dispatch('owned_edit',{'operation':'make_mesh_single_user',
        'params':{'name':local.name,'lease_id':lease}})
    assert linked_result['mesh_copy']['copied'] and local.as_pointer()==identity
    assert local.data!=linked and local.data.library is None and linked.library is not None
    assert local.data.shape_keys.library is None
    assert list(local.data.materials)==list(linked.materials)
    path=Path(folder)/'independent.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    target,peer=bpy.data.objects['TileGrid'],bpy.data.objects['LinkedPeer']
    assert target.data!=peer.data and target.data.shape_keys!=peer.data.shape_keys
    print(json.dumps({'native_mesh_single_user':'passed','object_skin_animation_context_preserved':True,
        'failed_copy_ids_removed':True,'three_frame_deformation_error_m':error,
        'peer_uv_unchanged':True,'no_op_allocates_nothing':True,'linked_mesh_local_copy_checked':True,
        'save_reopen_checked':True}))
