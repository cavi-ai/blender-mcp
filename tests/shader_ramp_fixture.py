"""Shared ramps, animation aliases and a full-coverage UV surface for native bakes."""
import json
import os
import runpy
from pathlib import Path
from unittest.mock import patch

import bpy

from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_shader_ramps import read, set_ramp

runpy.run_path(str(Path(__file__).with_name('shader_link_fixture.py')))
root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
tree=bpy.data.node_groups['SurfaceGraph']
palette=tree.nodes.new('ShaderNodeValToRGB');palette.name='Palette'
uv=tree.nodes.new('ShaderNodeUVMap');uv.name='RampUV';uv.uv_map='UVMap'
axes=tree.nodes.new('ShaderNodeSeparateXYZ');axes.name='UVComponents'
tree.links.new(uv.outputs['UV'],axes.inputs['Vector'])
tree.links.new(axes.outputs['X'],palette.inputs['Fac'])
mesh=bpy.data.meshes.new('RampPlane')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)],[],[(0,1,2,3)])
layer=mesh.uv_layers.new(name='UVMap')
for corner,coord in zip(layer.data,[(0,0),(1,0),(1,1),(0,1)],strict=True):corner.uv=coord
mesh.materials.append(bpy.data.materials['ArtistFinish'])
surface=bpy.data.objects.new('RampSurface',mesh);bpy.context.collection.objects.link(surface)
for name in ['AnimatedRamp','NlaRamp','DrivenRamp','ReferencedRamp','AliasRamp']:
    node=tree.nodes.new('ShaderNodeValToRGB');node.name=name
tree.nodes['NlaRamp'].color_ramp.elements[0].keyframe_insert('color',frame=1)
animation=tree.animation_data
action,slot=animation.action,animation.action_slot
strip=animation.nla_tracks.new().strips.new('PaletteAnimation',1,action)
strip.action_slot=slot;animation.action=None
tree.nodes['AnimatedRamp'].color_ramp.elements[0].keyframe_insert('color',frame=1)
tree.nodes['DrivenRamp'].color_ramp.elements[0].driver_add('color',0).driver.expression='.25'
reader=bpy.data.objects.new('RampReader',None);bpy.context.collection.objects.link(reader)
for name,owner,path in [('ReferencedRamp',tree,tree.nodes['ReferencedRamp'].color_ramp.path_from_id()),
    ('AliasRamp',bpy.data.materials['ArtistFinish'],'node_tree.nodes["Finish"].node_tree.'+tree.nodes['AliasRamp'].color_ramp.path_from_id())]:
    reader[name]=0.
    driver=reader.driver_add('['+json.dumps(name)+']').driver
    variable=driver.variables.new();variable.type='SINGLE_PROP'
    variable.targets[0].id_type='NODETREE' if owner==tree else 'MATERIAL'
    variable.targets[0].id=owner;variable.targets[0].data_path=path+'.elements[0].color[0]'
    driver.expression=variable.name
shader.update(tree)
params={'material_name':'ArtistFinish','group_path':['Finish'],'node':'Palette'}
before=shader.inspect(params)
with patch.object(shader,'node_report',side_effect=RuntimeError('ramp receipt failed')):
    try:
        set_ramp({**params,'node_settings':{'elements':[{'position':.4,'color':[2.5,.25,.125,.4]}]}})
    except RuntimeError as exc:
        assert str(exc)=='ramp receipt failed'
    else:raise AssertionError('Injected receipt failure succeeded')
assert shader.inspect(params)==before
animated=tree.nodes['AnimatedRamp'].color_ramp
pointers=[element.as_pointer() for element in animated.elements]
with patch.object(shader,'node_report',side_effect=RuntimeError('no-op receipt failed')):
    try:
        set_ramp({**params,'node':'AnimatedRamp','node_settings':read(animated)})
    except RuntimeError as exc:
        assert str(exc)=='no-op receipt failed'
    else:raise AssertionError('Injected no-op receipt failure succeeded')
assert [element.as_pointer() for element in animated.elements]==pointers


@bpy.app.handlers.persistent
def audit(*_):
    graph=bpy.data.node_groups['SurfaceGraph']
    palette=graph.nodes['Palette'].color_ramp
    result={'bakes':{},'guards':{n:read(graph.nodes[n].color_ramp) for n in
        ['AnimatedRamp','NlaRamp','DrivenRamp','ReferencedRamp','AliasRamp']},
        'plane':{'vertices':[list(v.co) for v in bpy.data.meshes['RampPlane'].vertices],
                 'uv':[list(c.uv) for c in bpy.data.meshes['RampPlane'].uv_layers['UVMap'].data]}}
    for name in ['single','alpha','linear','constant','hsv']:
        path=root/(name+'.exr')
        if not path.exists():continue
        image=bpy.data.images.load(str(path),check_existing=False)
        try:
            pixels=list(image.pixels[:]);width,height=image.size;channels=image.channels
            values=[pixels[i:i+3] for i in range(0,len(pixels),channels)]
            row=values[(height//2)*width:(height//2+1)*width]
            error=None
            matched_source={'linear':'linear.blend','hsv':'ramps.blend'}.get(name)
            if matched_source==Path(bpy.data.filepath).name:
                error=max(abs(a-b) for i,rgb in enumerate(row)
                    for a,b in zip(rgb,palette.evaluate((i+.5)/width)[:3],strict=True))
            result['bakes'][name]={'min':[min(v[c] for v in values) for c in range(3)],
                'max':[max(v[c] for v in values) for c in range(3)],'center':row[width//2],
                'row':row,'native_evaluation_error':error}
        finally:bpy.data.images.remove(image)
    (root/'ramp-audit.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit)
bpy.app.handlers.load_post.append(audit)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))
