"""An empty material-function context with native definition rollback checks."""
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
params={'material_name':'ArtistFinish','group_path':['Finish']}
before=shader.inspect(params);groups=set(bpy.data.node_groups)
spec={'name':'FailedDefinition','interface':[
    {'name':'Signal','in_out':'INPUT','socket_type':'NodeSocketFloat','default_value':-.2,'min_value':-4,'max_value':4},
    {'name':'Result','in_out':'OUTPUT','socket_type':'NodeSocketFloat'}]}
def fail_report(*_):
    group=bpy.data.node_groups['FailedDefinition']
    for kind in ['NodeGroupInput','NodeGroupOutput']:
        group.nodes.new(kind)
    raise RuntimeError('definition receipt failed')
with patch.object(shader,'node_report',side_effect=fail_report):
    try:create({**params,'node':'FailedInstance','node_type':'ShaderNodeGroup','node_settings':{'node_tree':spec}})
    except RuntimeError as exc:assert str(exc)=='definition receipt failed'
    else:raise AssertionError('Injected definition receipt failure succeeded')
assert shader.inspect(params)==before and set(bpy.data.node_groups)==groups


@bpy.app.handlers.persistent
def audit(*_):
    result={}
    for name in ['authored-a','authored-b','authored-c']:
        path=root/(name+'.exr')
        if not path.exists():continue
        image=bpy.data.images.load(str(path),check_existing=False)
        try:
            values=[v for i,v in enumerate(image.pixels[:]) if i%image.channels<3]
            result[name]={'min':min(values),'max':max(values),'samples':len(values)}
        finally:bpy.data.images.remove(image)
    (root/'author-bakes.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit);bpy.app.handlers.load_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))
