"""Two faces with a rig, shape key and independent UV layers."""
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('shader_udim_fixture.py')))
surface = bpy.data.objects['TileGrid']
old = surface.data
mesh = bpy.data.meshes.new('FaceUVs')
mesh.from_pydata([(-1,-1,0),(0,-1,0),(0,1,0),(-1,1,0),
                  (1,-1,0),(1,1,0)], [], [(0,1,2,3),(1,4,5,2)])
surface.data = mesh
bpy.data.meshes.remove(old)
mesh.materials.append(bpy.data.materials['ArtistFinish'])
mesh.materials.append(bpy.data.materials['OtherFinish'])
uv = mesh.uv_layers.new(name='UVMap')
for corner, position in zip(uv.data, [(1.2,1.2),(1.8,1.2),(1.8,1.8),(1.2,1.8),
                                     (.2,.2),(.8,.2),(.8,.8),(.2,.8)], strict=True):
    corner.uv = position
other = mesh.uv_layers.new(name='Alternate')
for corner in other.data:
    corner.uv = (.4,.4)
mesh.uv_layers.active_index = 1
other.active_render = True
mesh.edges[0].use_seam = True
mesh.polygons[1].select = False
surface.shape_key_add(name='Basis')
lift = surface.shape_key_add(name='Lift')
lift.data[0].co.z = .2
group = surface.vertex_groups.new(name='Root')
group.add(list(range(6)), .8, 'REPLACE')
armature = bpy.data.armatures.new('Skeleton')
rig = bpy.data.objects.new('Skeleton', armature)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone = armature.edit_bones.new('Root')
bone.head, bone.tail = (0,0,0), (0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
modifier = surface.modifiers.new('Skin', 'ARMATURE')
modifier.object = rig
surface.parent = rig
tree = bpy.data.node_groups['ArtistSurface']
coordinate = tree.nodes.new('ShaderNodeUVMap')
coordinate.uv_map = 'UVMap'
tree.links.new(coordinate.outputs['UV'], tree.nodes['Pattern'].inputs['Vector'])
