"""An evaluated collection instance reuses the same named atlas as its source."""
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('export_uv_fixture.py')))
kit=bpy.data.collections.new('UvKit')
bpy.context.scene.collection.children.link(kit)
kit.objects.link(bpy.data.objects['Hero'])
bpy.context.scene.collection.objects.unlink(bpy.data.objects['Hero'])
instance=bpy.data.objects.new('Kit',None)
instance.instance_type='COLLECTION'
instance.instance_collection=kit
bpy.context.scene.collection.objects.link(instance)
original=bpy.data.objects['Hero'].data
mesh=bpy.data.meshes.new('SkinSource')
mesh.from_pydata([tuple(v.co) for v in original.vertices],[],[list(f.vertices) for f in original.polygons])
for source in original.uv_layers:
    layer=mesh.uv_layers.new(name=source.name)
    for a,b in zip(layer.uv,source.uv,strict=True):a.vector=b.vector
mesh.uv_layers['ShaderUV'].active_render=True
skin=bpy.data.objects.new('Skin',mesh)
bpy.context.scene.collection.objects.link(skin)
armature=bpy.data.armatures.new('Rig')
rig=bpy.data.objects.new('Rig',armature)
bpy.context.scene.collection.objects.link(rig)
for obj in list(bpy.context.selected_objects):obj.select_set(False)
rig.select_set(True)
bpy.context.view_layer.objects.active=rig
bpy.ops.object.mode_set(mode='EDIT')
bone=armature.edit_bones.new('Root')
bone.head,bone.tail=(0,0,0),(0,0,1)
bpy.ops.object.mode_set(mode='OBJECT')
group=skin.vertex_groups.new(name='Root')
group.add(list(range(4)),1,'REPLACE')
skin.modifiers.new('Armature','ARMATURE').object=rig
for frame,y in [(1,0),(3,.2)]:
    rig.pose.bones['Root'].location.y=y
    rig.pose.bones['Root'].keyframe_insert('location',frame=frame)
bpy.context.scene.frame_set(1)
