"""Authored nested surface groups with per-material controls and shared native inputs."""

import json

import bpy

from cavi_blender_mcp.blender_materials import CONFIG_TAG, DEFAULTS


def interface(tree):
    rough = tree.interface.new_socket('Roughness', in_out='INPUT', socket_type='NodeSocketFloat')
    rough.min_value, rough.max_value = 0., 1.
    rough.default_value = .45
    tint = tree.interface.new_socket('Tint', in_out='INPUT', socket_type='NodeSocketColor')
    tint.default_value = (.2, .3, .4, 1.)
    tree.interface.new_socket('Shader', in_out='OUTPUT', socket_type='NodeSocketShader')
    return tree.nodes.new('NodeGroupInput'), tree.nodes.new('NodeGroupOutput')


inner = bpy.data.node_groups.new('ArtistSurface', 'ShaderNodeTree')
source, sink = interface(inner)
shader = inner.nodes.new('ShaderNodeBsdfPrincipled')
shader.name = 'Hero Surface'
inner.links.new(source.outputs['Roughness'], shader.inputs['Roughness'])
inner.links.new(source.outputs['Tint'], shader.inputs['Base Color'])
inner.links.new(shader.outputs['BSDF'], sink.inputs['Shader'])
outer = bpy.data.node_groups.new('LayeredSurface', 'ShaderNodeTree')
source, sink = interface(outer)
layer = outer.nodes.new('ShaderNodeGroup')
layer.name, layer.node_tree = 'Inner Layer', inner
outer.links.new(source.outputs['Roughness'], layer.inputs['Roughness'])
outer.links.new(source.outputs['Tint'], layer.inputs['Tint'])
outer.links.new(layer.outputs['Shader'], sink.inputs['Shader'])
for name, roughness in [('ArtistFinish', .45), ('OtherFinish', .65), ('ManagedA', .45), ('ManagedB', .45)]:
    material = bpy.data.materials.new(name)
    material.use_nodes, material.use_fake_user = True, True
    material.node_tree.nodes.clear()
    group = material.node_tree.nodes.new('ShaderNodeGroup')
    group.name, group.node_tree = 'Finish Controls', outer
    group.inputs['Roughness'].default_value = roughness
    output = material.node_tree.nodes.new('ShaderNodeOutputMaterial')
    material.node_tree.links.new(group.outputs['Shader'], output.inputs['Surface'])
    material['artist_note'] = 'retain'
    if name.startswith('Managed'):
        material[CONFIG_TAG] = json.dumps(DEFAULTS, sort_keys=True)
