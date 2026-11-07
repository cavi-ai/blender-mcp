"""Shared nested shader with untouched mesh layers and rollback fault injection."""
import json
import os
from pathlib import Path
from unittest.mock import patch

import bpy

from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp import blender_shader_links as links
from cavi_blender_mcp.blender_materials import CONFIG_TAG, DEFAULTS
from cavi_blender_mcp.blender_shader_links import edit_links

root=Path(os.environ['CAVI_BLENDER_WORKSPACE'])
inner=bpy.data.node_groups.new('SurfaceGraph','ShaderNodeTree')
inner.interface.new_socket(name='Shader',in_out='OUTPUT',socket_type='NodeSocketShader')
for name,color in [('Warm',(.9,.08,.03,1)),('Cool',(.03,.2,.8,1))]:
    node=inner.nodes.new('ShaderNodeRGB')
    node.name=name
    node.outputs[0].default_value=color
gain=inner.nodes.new('ShaderNodeValue')
gain.name='Gain'
gain.outputs[0].default_value=.4
emission=inner.nodes.new('ShaderNodeEmission')
emission.name='Surface'
emission.inputs['Color'].default_value=(.1,.1,.1,1)
output=inner.nodes.new('NodeGroupOutput')
output.name='Result'
inner.links.new(inner.nodes['Warm'].outputs[0],emission.inputs['Color'])
inner.links.new(emission.outputs[0],output.inputs['Shader'])
a,b=[inner.nodes.new('ShaderNodeMath') for _ in range(2)]
a.name,b.name='MathA','MathB'
inner.links.new(a.outputs[0],b.inputs[0]).is_muted=True
inner.links.new(emission.outputs[0],a.inputs[1])
for name in ['ArtistFinish','OtherFinish','ManagedA','ManagedB']:
    material=bpy.data.materials.new(name)
    material.use_nodes=material.use_fake_user=True
    tree=material.node_tree
    tree.nodes.clear()
    group=tree.nodes.new('ShaderNodeGroup')
    group.name,group.node_tree='Finish',inner
    sink=tree.nodes.new('ShaderNodeOutputMaterial')
    sink.name='Output'
    tree.links.new(group.outputs[0],sink.inputs['Surface'])
    material['artist_note']='retain'
    if name.startswith('Managed'):
        material[CONFIG_TAG]=json.dumps(DEFAULTS,sort_keys=True)
surface=bpy.data.objects['Cube']
surface.data.materials.clear()
surface.data.materials.append(bpy.data.materials['ArtistFinish'])
surface.shape_key_add(name='Basis')
surface.shape_key_add(name='Lift').data[0].co.z+=.1
surface.vertex_groups.new(name='Root').add([0,1],.8,'REPLACE')
peer=surface.copy()
peer.name='Peer'
bpy.context.collection.objects.link(peer)
bpy.context.scene.render.engine='CYCLES'
bpy.context.scene.cycles.device='CPU'

args={'material_name':'ArtistFinish','group_path':['Finish'],'node':'Surface',
      'action':'connect','update_existing':True,'inputs':{'Color':{'node':'Cool','socket':'Color'}}}
shader.update(inner)
original=shader.inspect(args)
configs={n:bpy.data.materials[n][CONFIG_TAG] for n in ['ManagedA','ManagedB']}
bpy.data.materials['ManagedA'][shader.PROVENANCE_TAG]='prior'
for options in [args,{**args,'node':'MathB','inputs':{'Value':{'node':'Gain','socket':'Value'}}},
                {**args,'node':'MathA','inputs':{'Value_001':{'node':'Gain','socket':'Value'}}}]:
    prior=shader.inspect(options)
    with patch.object(shader,'node_report',side_effect=RuntimeError('receipt failed')):
        try:
            edit_links(options)
        except RuntimeError as exc:
            assert str(exc)=='receipt failed'
        else:
            raise AssertionError('Receipt failure succeeded')
    assert shader.inspect(options)==prior
after=shader.inspect(args)
assert after==original,{k:(original[k],after[k]) for k in original if original[k]!=after[k]}
assert all(bpy.data.materials[n][CONFIG_TAG]==value for n,value in configs.items())
assert bpy.data.materials['ManagedA'][shader.PROVENANCE_TAG]=='prior'
assert shader.PROVENANCE_TAG not in bpy.data.materials['ManagedB']
native_apply=links.apply


def partial_failure(tree,changes,connect):
    native_apply(tree,changes[:1],connect)
    raise RuntimeError('partial link edit failed')


batch={**args,'inputs':{**args['inputs'],'Strength':{'node':'Gain','socket':'Value'}}}
with patch.object(links,'apply',side_effect=partial_failure):
    try:
        edit_links(batch)
    except RuntimeError as exc:
        assert str(exc)=='partial link edit failed'
    else:
        raise AssertionError('Partial edit failure succeeded')
assert shader.inspect(args)==original
assert all(bpy.data.materials[n][CONFIG_TAG]==value for n,value in configs.items())


@bpy.app.handlers.persistent
def audit(*_):
    mesh=bpy.data.objects['Cube'].data
    result={'mesh':mesh.name,'users':mesh.users,'vertices':[list(v.co) for v in mesh.vertices],
        'faces':[list(f.vertices) for f in mesh.polygons],
        'uvs':{l.name:[list(c.uv) for c in l.data] for l in mesh.uv_layers},
        'weights':[[(g.group,g.weight) for g in v.groups] for v in mesh.vertices],
        'keys':{k.name:[list(c.co) for c in k.data] for k in mesh.shape_keys.key_blocks},
        'selected':sorted(o.name for o in bpy.context.selected_objects),
        'active':bpy.context.view_layer.objects.active.name,'mode':bpy.context.mode,
        'slots':{o.name:[(s.link,s.material.name) for s in o.material_slots] for o in bpy.data.objects if o.type=='MESH'},
        'notes':{n:bpy.data.materials[n]['artist_note'] for n in ['ArtistFinish','OtherFinish','ManagedA','ManagedB']},
        'groups':sorted(g.name for g in bpy.data.node_groups),'samples':{}}
    for name in ['baseline','candidate','disconnected']:
        path=root/(name+'.exr')
        if path.exists():
            image=bpy.data.images.load(str(path),check_existing=False)
            try:
                index=(image.size[0]*(image.size[1]//2)+image.size[0]//2)*image.channels
                result['samples'][name]=list(image.pixels[index:index+3])
            finally:
                bpy.data.images.remove(image)
    (root/'shader-link-audit.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit)
bpy.app.handlers.load_post.append(audit)
bpy.context.preferences.filepaths.save_version=0
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'))
