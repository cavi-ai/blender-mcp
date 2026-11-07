"""Node creation rollback and evaluated procedural samples in a private source."""
import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import bpy

from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_shader_nodes import create

runpy.run_path(str(Path(__file__).with_name('shader_link_fixture.py')))
root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
params={'material_name':'ArtistFinish','group_path':['Finish']}
before=shader.inspect(params)
tree=bpy.data.node_groups['SurfaceGraph']
with patch.object(shader,'node_report',side_effect=RuntimeError('node receipt failed')):
    try:
        create({**params,'node':'FailedNoise','node_type':'ShaderNodeTexNoise',
                'node_settings':{'noise_dimensions':'4D','normalize':True}})
    except RuntimeError as exc:
        assert str(exc)=='node receipt failed'
    else:
        raise AssertionError('Failed creation returned success')
assert shader.inspect(params)==before and 'FailedNoise' not in tree.nodes
root_params={'material_name':'ArtistFinish'}
root_before=shader.inspect(root_params)
with patch.object(shader,'node_report',side_effect=RuntimeError('node receipt failed')):
    try:
        create({**root_params,'node':'FailedOutput','node_type':'ShaderNodeOutputMaterial',
                'node_settings':{'is_active_output':True}})
    except RuntimeError as exc:
        assert str(exc)=='node receipt failed'
    else:
        raise AssertionError('Failed output creation returned success')
assert shader.inspect(root_params)==root_before
assert bpy.data.materials['ArtistFinish'].node_tree.nodes['Output'].is_active_output


@bpy.app.handlers.persistent
def samples(*_):
    if not (root/'noise.exr').exists() or not (root/'candidate.exr').exists():return
    arrays={}
    for name in ['noise','candidate']:
        image=bpy.data.images.load(str(root/(name+'.exr')),check_existing=False)
        try:
            values=list(image.pixels[:])
            arrays[name]=[v for index,v in enumerate(values) if index%image.channels<3]
        finally:
            bpy.data.images.remove(image)
    assert len(arrays['noise'])==len(arrays['candidate'])
    (root/'shader-node-samples.json').write_text(json.dumps({
        'samples':len(arrays['noise']),
        'noise_range':[min(arrays['noise']),max(arrays['noise'])],
        'maximum_abs_error':max(abs(c-n*.5) for n,c in zip(arrays['noise'],arrays['candidate'],strict=True))}))


bpy.app.handlers.save_post.append(samples)
bpy.app.handlers.load_post.append(samples)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))
