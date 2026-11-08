"""Existing procedural nodes, referenced controls and native rollback snapshots."""
import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import bpy

from cavi_blender_mcp import blender_shader_controls as controls
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_shader_controls import set_controls

runpy.run_path(str(Path(__file__).with_name('shader_ramp_fixture.py')))
root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
tree=bpy.data.node_groups['SurfaceGraph']
uv=tree.nodes.new('ShaderNodeUVMap');uv.name='ExistingUV';uv.uv_map='UVMap'
noise=tree.nodes.new('ShaderNodeTexNoise');noise.name='ExistingNoise'
noise.noise_dimensions='3D';noise.normalize=False
math=tree.nodes.new('ShaderNodeMath');math.name='ExistingMath';math.operation='ADD'
math.inputs[1].default_value=.25
tree.links.new(uv.outputs['UV'],noise.inputs['Vector']);tree.links.new(noise.outputs['Fac'],math.inputs[0])
mesh=bpy.data.meshes['RampPlane'];alt=mesh.uv_layers.new(name='AltUV')
for source,target in zip(mesh.uv_layers['UVMap'].data,alt.data,strict=True):target.uv=source.uv*.5
guard=tree.nodes.new('ShaderNodeTexNoise');guard.name='GuardNoise';guard.normalize=True
reader=bpy.data.objects['RampReader'];reader['normalize']=0.
driver=reader.driver_add('["normalize"]').driver
variable=driver.variables.new();variable.type='SINGLE_PROP';variable.targets[0].id_type='MATERIAL'
variable.targets[0].id=bpy.data.materials['ArtistFinish']
variable.targets[0].data_path='node_tree.nodes["Finish"].node_tree.nodes["GuardNoise"].normalize'
driver.expression=variable.name
shader.update(tree)
params={'material_name':'ArtistFinish','group_path':['Finish'],'node':'ExistingMath'}
before=shader.inspect(params)
with patch.object(shader,'node_report',side_effect=RuntimeError('control receipt failed')):
    try:set_controls({**params,'node_settings':{'operation':'MULTIPLY_ADD'}})
    except RuntimeError as exc:assert str(exc)=='control receipt failed'
    else:raise AssertionError('Injected settings receipt failure succeeded')
assert shader.inspect(params)==before
native_update=controls.update
first=True
def lose_link_once(graph):
    global first
    native_update(graph)
    if first:
        first=False
        graph.links.remove(math.inputs[0].links[0])
        math.inputs[1].default_value=.99
with patch.object(controls,'update',side_effect=lose_link_once):
    try:set_controls({**params,'node_settings':{'operation':'MULTIPLY_ADD'}})
    except RuntimeError as exc:assert 'changed shader connections' in str(exc)
    else:raise AssertionError('Connection loss was accepted')
assert shader.inspect(params)==before
material=bpy.data.materials['ArtistFinish'];output=material.node_tree.nodes.new('ShaderNodeOutputMaterial')
output.name='AlternativeOutput';material.node_tree.nodes['Output'].is_active_output=True
params={'material_name':'ArtistFinish','node':'AlternativeOutput'}
before=shader.inspect(params)
with patch.object(shader,'node_report',side_effect=RuntimeError('output receipt failed')):
    try:set_controls({**params,'node_settings':{'is_active_output':True}})
    except RuntimeError as exc:assert str(exc)=='output receipt failed'
    else:raise AssertionError('Injected output receipt failure succeeded')
assert shader.inspect(params)==before and material.node_tree.nodes['Output'].is_active_output


@bpy.app.handlers.persistent
def audit(*_):
    paths={name:root/(name+'.exr') for name in ['controls-baseline','controls-noise','controls-math']}
    if not all(path.exists() for path in paths.values()):return
    arrays={}
    for name,path in paths.items():
        image=bpy.data.images.load(str(path),check_existing=False)
        try:arrays[name]=[v for i,v in enumerate(image.pixels[:]) if i%image.channels<3]
        finally:bpy.data.images.remove(image)
    baseline,noise,math=(arrays[name] for name in paths)
    (root/'control-bakes.json').write_text(json.dumps({
        'samples':len(noise),'mode_change_max_difference':max(abs(a-b) for a,b in zip(baseline,noise,strict=True)),
        'multiply_max_error':max(abs(a*.25-b) for a,b in zip(noise,math,strict=True))}))


bpy.app.handlers.save_post.append(audit);bpy.app.handlers.load_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))
