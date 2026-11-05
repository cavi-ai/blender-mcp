"""Native socket baking preserves signed precision, UV context and actor identity."""
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_bake import state

with tempfile.TemporaryDirectory() as folder:
    root=Path(folder)
    bridge._workspace=root
    os.environ['CAVI_BLENDER_WORKSPACE']=folder
    runpy.run_path(str(Path(__file__).with_name('shader_bake_fixture.py')))
    shader.set_image({'material_name':'ArtistFinish','group_path':['Finish Controls','Inner Layer'],
        'node':'Pattern','image':{'path':'glaze.<UDIM>.exr','tiles':[1001,1002,1011,1012],
            'color_space':'Non-Color'}},root)
    scene=bpy.context.scene
    subject=bpy.data.objects['TileGrid']
    def read(path, points):
        image=bpy.data.images.load(str(path),check_existing=False)
        try:
            image.colorspace_settings.name='Non-Color'
            return [tuple(image.pixels[(y*image.size[0]+x)*4:(y*image.size[0]+x)*4+3]) for x,y in points]
        finally:
            bpy.data.images.remove(image)
    ownership=bridge.dispatch('session_control',{'action':'inspect'})
    lease=bridge.dispatch('session_control',{'action':'claim','owner':'channel-author',
        'expected_project':ownership['project_id']})['lease_id']
    def edit(operation,**params):
        return bridge.dispatch('owned_edit',{'operation':operation,'params':{**params,'lease_id':lease}})
    edit('scene_authoring',action='render',definition={'path':'identity-reference.exr','camera':'TileCamera',
        'engine':'cycles','device':'CPU','width':64,'height':64,'samples':1,'file_format':'exr',
        'bit_depth':'32','view_transform':'Raw','denoise':False,'max_pixels':4096,
        'frame':None,'cycles_time_limit':30,'threads':2,'transparent':False,'exposure':0,'gamma':1})
    reference=read(root/'identity-reference.exr',[(32,32)])[0][0]
    scene.render.engine='BLENDER_WORKBENCH'
    scene.cycles.sample_clamp_direct=.25
    def snapshot():
        return {'ids':ids(),'settings':state(scene),'clamp':scene.cycles.sample_clamp_direct,
            'bake_type':scene.cycles.bake_type,
            'graphs':[shader.inspect({'material_name':'ArtistFinish','group_path':path})
                      for path in [[],['Finish Controls'],['Finish Controls','Inner Layer']]],
            'object':subject.as_pointer(),'mesh':subject.data,'frame':scene.frame_current,
            'slots':[(s.link,s.material) for s in subject.material_slots],
            'uv_active':subject.data.uv_layers.active_index,
            'uv_render':[u.active_render for u in subject.data.uv_layers],
            'uvs':[[tuple(c.uv) for c in u.data] for u in subject.data.uv_layers],
            'keys':[[tuple(v.co) for v in k.data] for k in subject.data.shape_keys.key_blocks],
            'selection':set(bpy.context.selected_objects),'active':bpy.context.view_layer.objects.active,
            'visibility':[(o,o.hide_render,o.hide_viewport,o.hide_get()) for o in scene.objects]}
    before=snapshot()
    def bake(path, source, **options):
        return edit('bake_shader',name=subject.name,path=path,source=source,
            uv_layer='BakeUV',resolution=64,samples=1,margin=0,**options)
    texture={'material':'ArtistFinish','group_path':['Finish Controls','Inner Layer'],
        'node':'Pattern','socket':'Color','direction':'OUTPUT','role':'data'}
    receipt=bake('channel.exr',texture)
    assert receipt['bit_depth']==32 and receipt['color_space']=='Non-Color'
    samples=read(root/'channel.exr',[(16,16),(48,16),(16,48),(48,48)])
    expected=[(n/1000,-.25,3.5) for n in [1001,1002,1011,1012]]
    error=max(abs(a-b) for left,right in zip(samples,expected,strict=True) for a,b in zip(left,right,strict=True))
    assert error<1e-6,(samples,expected,error)
    assert snapshot()==before
    mask={'material':'ArtistFinish','group_path':['Finish Controls','Inner Layer'],
        'node':'Hero Surface','socket':'Roughness','direction':'INPUT','role':'data'}
    png=bake('roughness.png',mask)
    assert png['bit_depth']==16 and (root/'roughness.png').read_bytes()[24]==16
    value=read(root/'roughness.png',[(32,32)])[0][0]
    assert abs(value-.731234)<2e-5,value
    identity=bake('identity.exr',{'material':'ArtistFinish','node':'Identity','socket':'Random','role':'data'})
    random=read(root/'identity.exr',[(32,32)])[0][0]
    assert abs(random-reference)<1e-6,(reference,random)
    assert identity['source']['channels']==['R','G','B'] and snapshot()==before
    tint={'material':'ArtistFinish','node':'Finish Controls',
          'socket':bpy.data.materials['ArtistFinish'].node_tree.nodes['Finish Controls'].inputs['Tint'].identifier,
          'direction':'INPUT','role':'color'}
    color=bake('color.png',tint)
    encoded=read(root/'color.png',[(32,32)])[0]
    expected_color=[1.055*v**(1/2.4)-.055 for v in [.123456,.345678,.567891]]
    assert color['color_space']=='sRGB' and max(abs(a-b) for a,b in zip(encoded,expected_color,strict=True))<2e-5
    linear=bake('color.exr',tint)
    linear_values=read(root/'color.exr',[(32,32)])[0]
    assert max(abs(a-b) for a,b in zip(linear_values,[.123456,.345678,.567891],strict=True))<1e-6
    assert snapshot()==before
    # Invalid socket and non-atlas UVs must leave both IDs and destination untouched.
    for filename,options in [('invalid.exr',{'source':{**mask,'socket':'BSDF','direction':'OUTPUT'}}),
                             ('not-atlas.exr',{'uv_layer':'ShaderUV'})]:
        try:
            edit('bake_shader',name=subject.name,path=filename,source=options.pop('source',mask),
                 uv_layer=options.pop('uv_layer','BakeUV'),resolution=64,samples=1,**options)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid source/UV was accepted')
        assert not (root/filename).exists() and snapshot()==before
    try:
        bake('clipped.png',texture)
    except ValueError:
        pass
    else:
        raise AssertionError('Signed/HDR samples were clipped into PNG')
    assert not (root/'clipped.png').exists() and snapshot()==before
    from cavi_blender_mcp import blender_shader_bake
    with patch.object(blender_shader_bake,'write',side_effect=RuntimeError('encoder failure')):
        try:
            bake('failed.exr',mask)
        except RuntimeError as exc:
            assert str(exc)=='encoder failure'
        else:
            raise AssertionError('Expected an encoder failure')
    assert not (root/'failed.exr').exists() and snapshot()==before
    print(json.dumps({'native_shader_bake':'passed','signed_hdr_error':error,
        'shader_uv_and_bake_uv_independent':True,'nested_input':value,
        'object_random_reference':reference,'object_random_bake':random,
        'modifiers_and_shape_keys_preserved':True,'failure_restored_state_and_removed_file':True}))
