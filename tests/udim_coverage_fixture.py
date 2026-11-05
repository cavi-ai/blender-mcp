"""Material-filtered source UVs, explicit UV0 sampling and an alternate UV layer."""

import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('shader_udim_fixture.py')))
surface = bpy.data.objects['TileGrid']
other = surface.data.uv_layers.new(name='CollapsedUV')
for corner in other.data:
    corner.uv = (.5,.5)
other.active_render = True
shared = bpy.data.objects.new('OtherSurface', surface.data)
bpy.context.scene.collection.objects.link(shared)
shared.material_slots[0].link = 'OBJECT'
shared.material_slots[0].material = bpy.data.materials['OtherFinish']
shared.hide_render = True
tree = bpy.data.node_groups['ArtistSurface']
uv = tree.nodes.new('ShaderNodeUVMap')
uv.uv_map = 'UVMap'
tree.links.new(uv.outputs['UV'], tree.nodes['Pattern'].inputs['Vector'])
empty = bpy.data.images.new('UnavailableTiles', width=1, height=1, tiled=True)
empty.tiles.new(1012)
empty.use_fake_user = True
