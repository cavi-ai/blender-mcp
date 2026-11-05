"""Linked skinned meshes with animated keys, a driver and object material overrides."""
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('uv_transform_fixture.py')))
surface = bpy.data.objects['TileGrid']
surface.location, surface.scale = (.3,.2,.1), (-1,2,.5)
surface.rotation_euler = (.1,.2,.3)
surface.data['asset_hint'] = 'tiled skin'
surface.data.use_fake_user = True
surface.material_slots[1].link = 'OBJECT'
surface.material_slots[1].material = bpy.data.materials['ArtistFinish']
peer = surface.copy()
peer.name = 'LinkedPeer'
peer.location.x += 3
bpy.context.scene.collection.objects.link(peer)
key = surface.data.shape_keys.key_blocks['Lift']
for frame, value in [(1,0),(11,.8)]:
    key.value = value
    key.keyframe_insert(data_path='value', frame=frame)
rig = surface.parent
rig['gain'] = .3
blink = surface.shape_key_add(name='Blink')
driver = blink.driver_add('value').driver
variable = driver.variables.new()
variable.name, variable.targets[0].id = 'gain', rig
variable.targets[0].data_path = '["gain"]'
driver.expression = 'gain'
bone = rig.pose.bones['Root']
for frame, value in [(1,0),(11,.3)]:
    bone.rotation_euler.z = value
    bone.keyframe_insert(data_path='rotation_euler', frame=frame)
bpy.context.scene.frame_set(1)
