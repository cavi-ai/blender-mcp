"""Two UV layouts and a shared material owner without the atlas."""

import os
from pathlib import Path

import bpy

from cavi_blender_mcp import blender_materials

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.ops.mesh.primitive_plane_add(size=2)
subject = bpy.context.object
subject.name = 'Subject'
uv = subject.data.uv_layers.active
uv.name, uv.active_render = 'UVMap', True
atlas = subject.data.uv_layers.new(name='Atlas', do_init=False)
for index, coordinate in enumerate(((0, 0), (1, 0), (1, 1), (0, 1))):
    uv.data[index].uv = (coordinate[0] * .4 + .05, coordinate[1])
    atlas.data[index].uv = (coordinate[0] * .4 + .55, coordinate[1])
subject.data.uv_layers.active_index = 0
uv.active_render = True
atlas.active_render = False

for name, color in [('color', None), ('normal', (.5, .5, 1, 1))]:
    image = bpy.data.images.new(name, width=4, height=4, float_buffer=True)
    pixels = []
    for y in range(4):
        for x in range(4):
            pixels.extend(color or ((1, 0, 0, 1) if x < 2 else (0, 0, 1, 1)))
    image.pixels = pixels
    settings = bpy.context.scene.render.image_settings
    settings.file_format, settings.color_mode, settings.color_depth = 'PNG', 'RGBA', '16'
    image.save_render(str(root / (name + '.png')))
    bpy.data.images.remove(image)

blender_materials.assign({'names': ['Subject'], 'material_name': 'SharedFinish',
    'base_color_texture': 'color.png', 'normal_texture': 'normal.png', 'uv_layer': 'UVMap'},
    root, lambda name, mesh=False: bpy.data.objects[name])
peer = subject.copy()
peer.data = subject.data.copy()
peer.name, peer.hide_render = 'Peer', True
peer.data.uv_layers.remove(peer.data.uv_layers['Atlas'])
bpy.context.scene.collection.objects.link(peer)

world = bpy.data.worlds.new('UV World')
world.use_nodes = True
world.node_tree.nodes['Background'].inputs['Color'].default_value = (1, 1, 1, 1)
world.node_tree.nodes['Background'].inputs['Strength'].default_value = 1
bpy.context.scene.world = world
camera = bpy.data.objects.new('UV Camera', bpy.data.cameras.new('UV Camera'))
camera.location = (0, 0, 3)
camera.data.type, camera.data.ortho_scale = 'ORTHO', 2.2
bpy.context.scene.collection.objects.link(camera)
bpy.context.scene.camera = camera
