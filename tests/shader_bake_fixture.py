"""Deformed shared mesh with separate shader/bake UVs and nested channel sources."""
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('shader_udim_fixture.py')))
surface=bpy.data.objects['TileGrid']
old=surface.data
mesh=bpy.data.meshes.new('ChannelSurface')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0),(3,0,0),(4,0,0),(3,1,0)],
                 [],[(0,1,2,3),(4,5,6)])
surface.data=mesh
bpy.data.meshes.remove(old)
mesh.materials.append(bpy.data.materials['ArtistFinish'])
mesh.materials.append(bpy.data.materials['OtherFinish'])
mesh.polygons[1].material_index=1
shader=mesh.uv_layers.new(name='ShaderUV')
atlas=mesh.uv_layers.new(name='BakeUV')
for layer,scale in [(shader,2),(atlas,1)]:
    for corner,uv in zip(layer.data,[(0,0),(scale,0),(scale,scale),(0,scale),(0,0),(1,0),(0,1)],strict=True):
        corner.uv=uv
shader.active_render=True
mesh.uv_layers.active_index=1
surface.shape_key_add(name='Basis')
lift=surface.shape_key_add(name='Lift')
lift.data[0].co.z=.1
lift.value=.5
armature=bpy.data.armatures.new('ChannelRig')
rig=bpy.data.objects.new('ChannelRig',armature)
bpy.context.scene.collection.objects.link(rig)
bpy.context.view_layer.objects.active=rig
rig.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
bone=armature.edit_bones.new('Root')
bone.head,bone.tail=(0,0,0),(0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
group=surface.vertex_groups.new(name='Root')
group.add(list(range(7)),1,'REPLACE')
modifier=surface.modifiers.new('Skin','ARMATURE')
modifier.object=rig
rig.pose.bones['Root'].location.z=.05
peer=surface.copy()
peer.name,peer.hide_render='ChannelPeer',True
bpy.context.scene.collection.objects.link(peer)
root=bpy.data.materials['ArtistFinish'].node_tree
root.nodes['Finish Controls'].inputs['Roughness'].default_value=.731234
root.nodes['Finish Controls'].inputs['Tint'].default_value=(.123456,.345678,.567891,1)
info=root.nodes.new('ShaderNodeObjectInfo')
info.name='Identity'
emission=root.nodes.new('ShaderNodeEmission')
root.links.new(info.outputs['Random'],emission.inputs['Color'])
output=next(n for n in root.nodes if n.type=='OUTPUT_MATERIAL')
root.links.new(emission.outputs[0],output.inputs['Surface'])
bpy.context.view_layer.update()
