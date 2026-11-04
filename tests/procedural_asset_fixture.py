"""Artist-authored fence graph shared by independent object modifiers."""

import bpy

tree = bpy.data.node_groups.new('FenceGenerator', 'GeometryNodeTree')
for direction in ['INPUT', 'OUTPUT']:
    tree.interface.new_socket('Geometry', in_out=direction, socket_type='NodeSocketGeometry')
for name, kind, default, low, high in [
    ('Count', 'NodeSocketInt', 3, 1, 100),
    ('Spacing', 'NodeSocketFloat', 1., .1, 10.),
    ('Height', 'NodeSocketFloat', 1.2, .1, 5.),
    ('Width', 'NodeSocketFloat', .15, .02, .5),
]:
    socket = tree.interface.new_socket(name, in_out='INPUT', socket_type=kind)
    socket.default_value, socket.min_value, socket.max_value = default, low, high
    socket.force_non_field = True
tree.interface.new_socket('Offset', in_out='INPUT', socket_type='NodeSocketVector')
tree.interface.new_socket('Finish', in_out='INPUT', socket_type='NodeSocketMaterial')
tree.interface.new_socket('Label', in_out='INPUT', socket_type='NodeSocketString').default_value = 'Fence'
tree.interface.new_socket('Tint', in_out='INPUT', socket_type='NodeSocketColor')
tree.interface.new_socket('Enabled', in_out='INPUT', socket_type='NodeSocketBool')
tree.interface.new_socket('Rotation', in_out='INPUT', socket_type='NodeSocketRotation')
tree.interface.new_socket('Mask', in_out='INPUT', socket_type='NodeSocketFloat')
nodes, links = tree.nodes, tree.links
source, sink = nodes.new('NodeGroupInput'), nodes.new('NodeGroupOutput')
line = nodes.new('GeometryNodeMeshLine')
line.mode = 'OFFSET'
step = nodes.new('ShaderNodeCombineXYZ')
size = nodes.new('ShaderNodeCombineXYZ')
cube = nodes.new('GeometryNodeMeshCube')
instances = nodes.new('GeometryNodeInstanceOnPoints')
realize = nodes.new('GeometryNodeRealizeInstances')
transform = nodes.new('GeometryNodeTransform')
finish = nodes.new('GeometryNodeSetMaterial')
attribute = nodes.new('GeometryNodeStoreNamedAttribute')
attribute.data_type, attribute.domain = 'FLOAT', 'POINT'
attribute.inputs['Name'].default_value = 'AuthoredMask'
attribute.inputs['Value'].default_value = .25
for output, input in [
    (source.outputs['Count'], line.inputs['Count']),
    (source.outputs['Spacing'], step.inputs['X']), (step.outputs[0], line.inputs['Offset']),
    (source.outputs['Width'], size.inputs['X']), (source.outputs['Width'], size.inputs['Y']),
    (source.outputs['Height'], size.inputs['Z']), (size.outputs[0], cube.inputs['Size']),
    (line.outputs['Mesh'], instances.inputs['Points']), (cube.outputs['Mesh'], instances.inputs['Instance']),
    (instances.outputs['Instances'], realize.inputs['Geometry']),
    (realize.outputs['Geometry'], transform.inputs['Geometry']),
    (source.outputs['Offset'], transform.inputs['Translation']),
    (transform.outputs['Geometry'], finish.inputs['Geometry']),
    (source.outputs['Finish'], finish.inputs['Material']), (finish.outputs[0], attribute.inputs['Geometry']),
    (attribute.outputs['Geometry'], sink.inputs[0]),
]:
    links.new(output, input)
for name in ['Fence', 'OtherFence']:
    mesh = bpy.data.meshes.new(name)
    value = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(value)
    value.modifiers.new('Generator', 'NODES').node_group = tree
for name, color in [('Blue', (.05, .2, .8, 1)), ('Gold', (.8, .45, .05, 1))]:
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    material.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = color
bpy.context.view_layer.update()
