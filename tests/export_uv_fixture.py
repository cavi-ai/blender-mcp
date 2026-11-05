"""Shared triangulated mesh with distinct shader/atlas coordinates and a morph."""
import bpy

for value in list(bpy.data.objects):bpy.data.objects.remove(value,do_unlink=True)
mesh=bpy.data.meshes.new('UvSource')
mesh.from_pydata([(0,0,0),(1,0,0),(1,1,0),(0,1,0)],[],[(0,1,2),(0,2,3)])
for name,coords in [('ShaderUV',[(0,0),(0,2),(2,2),(2,0)]),
                    ('Atlas',[(.1,.1),(.9,.1),(.9,.9),(.1,.9)])]:
    layer=mesh.uv_layers.new(name=name)
    for corner in mesh.loops:layer.uv[corner.index].vector=coords[corner.vertex_index]
    layer.data[0].pin_uv=True
mesh.uv_layers['ShaderUV'].active_render=True
mesh.uv_layers.active_index=1
material=bpy.data.materials.new('Finish')
material.use_nodes=True
mesh.materials.append(material)
for name in ['Hero','Peer']:
    value=bpy.data.objects.new(name,mesh)
    bpy.context.scene.collection.objects.link(value)
value=bpy.data.objects['Hero']
value.shape_key_add(name='Basis')
key=value.shape_key_add(name='Lift')
key.data[0].co.z=.2
key.value=.25
key.keyframe_insert('value',frame=1)
key.value=.75
key.keyframe_insert('value',frame=3)
value.material_slots[0].link='OBJECT'
value.material_slots[0].material=material
bpy.context.view_layer.objects.active=value
value.select_set(True)
bpy.context.scene.frame_set(1)
