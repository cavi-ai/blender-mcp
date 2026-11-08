"""Native material-function library, colliding local group and rollback checks."""
import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import bpy

from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_shader_nodes import create

runpy.run_path(str(Path(__file__).with_name('shader_ramp_fixture.py')))
root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
studio=bpy.data.node_groups.new('StudioFinish','ShaderNodeTree');studio.use_fake_user=True
studio.interface.new_socket(name='Signal',in_out='INPUT',socket_type='NodeSocketFloat')
studio.interface.new_socket(name='Result',in_out='OUTPUT',socket_type='NodeSocketFloat')
entry=studio.nodes.new('NodeGroupInput');exit=studio.nodes.new('NodeGroupOutput')
gain=studio.nodes.new('ShaderNodeMath');gain.name='StudioGain';gain.operation='MULTIPLY'
gain.inputs[1].default_value=.25
studio.links.new(entry.outputs['Signal'],gain.inputs[0]);studio.links.new(gain.outputs[0],exit.inputs['Result'])
geo=bpy.data.node_groups.new('GeometrySentinel','GeometryNodeTree');geo.use_fake_user=True
bpy.data.libraries.write(str(root/'finishes.blend'),{studio,geo})
# The collision has a different value; using its name instead of the append receipt fails the bakes.
gain.inputs[1].default_value=.9
bridge=bpy.data.node_groups.new('RecursiveBridge','ShaderNodeTree');bridge.use_fake_user=True
bridge.nodes.new('ShaderNodeGroup').node_tree=bpy.data.node_groups['SurfaceGraph']
params={'material_name':'ArtistFinish','group_path':['Finish']}
before=shader.inspect(params);users=studio.users
with patch.object(shader,'node_report',side_effect=RuntimeError('group receipt failed')):
    try:create({**params,'node':'FailedInstance','node_type':'ShaderNodeGroup','node_settings':{'node_tree':studio.name}})
    except RuntimeError as exc:assert str(exc)=='group receipt failed'
    else:raise AssertionError('Injected group receipt failure succeeded')
assert shader.inspect(params)==before and studio.users==users
shader.update(bpy.data.node_groups['SurfaceGraph'])


@bpy.app.handlers.persistent
def audit(*_):
    result={'bakes':{},'collision_gain':bpy.data.node_groups['StudioFinish'].nodes['StudioGain'].inputs[1].default_value}
    for name in ['group-a','group-b','group-a-shared','group-b-shared']:
        path=root/(name+'.exr')
        if not path.exists():continue
        image=bpy.data.images.load(str(path),check_existing=False)
        try:
            values=[v for i,v in enumerate(image.pixels[:]) if i%image.channels<3]
            result['bakes'][name]={'min':min(values),'max':max(values),'samples':len(values)}
        finally:bpy.data.images.remove(image)
    (root/'group-audit.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit);bpy.app.handlers.load_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))
