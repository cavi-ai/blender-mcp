"""Shared geometry and nested material groups with image, action and object references."""
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('shader_udim_fixture.py')))
surface=bpy.data.objects['TileGrid']
surface.location.x=-.55
surface.scale=(.5,.75,1)
peer=surface.copy()
peer.name,peer.location.x='FinishPeer',.55
bpy.context.scene.collection.objects.link(peer)
peer.material_slots[0].link='OBJECT'
peer.material_slots[0].material=bpy.data.materials['OtherFinish']
second=surface.copy()
second.name,second.hide_render='SecondTarget',True
bpy.context.scene.collection.objects.link(second)
material=bpy.data.materials['ArtistFinish']
wrapper=material.node_tree.nodes['Finish Controls'].node_tree
reuse=material.node_tree.nodes.new('ShaderNodeGroup')
reuse.name,reuse.node_tree='Reused Controls',wrapper
anchor=material.node_tree.nodes.new('ShaderNodeTexCoord')
anchor.name,anchor.object='Scene Anchor',surface
inner=bpy.data.node_groups['ArtistSurface']
gain=inner.nodes.new('ShaderNodeValue')
gain.name='Variant Gain'
gain.outputs[0].default_value=1
inner.links.new(gain.outputs[0],next(n for n in inner.nodes if n.type=='EMISSION').inputs['Strength'])
animated=inner.nodes.new('ShaderNodeValue')
animated.name='Animated Control'
for frame in [1,11]:
    animated.outputs[0].default_value=.4
    animated.outputs[0].keyframe_insert(data_path='default_value',frame=frame)
bpy.context.scene.frame_set(1)
bpy.context.scene.camera.data.ortho_scale=2.4
