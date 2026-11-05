"""Authored material with declared float/PNG16 tiles and an undeclared neighbor."""

import os
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('shader_texture_fixture.py')))
root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
scene = bpy.context.scene
colors = {1001: (.8, .02, .02, 1.), 1002: (.02, .8, .02, 1.),
          1011: (.02, .02, .8, 1.), 1012: (.8, .8, .02, 1.)}
for number, size in [(1001, (2, 2)), (1002, (4, 2)), (1011, (2, 4)), (1012, (2, 2))]:
    for suffix, format, depth in [('png', 'PNG', '16'), ('exr', 'OPEN_EXR', '32')]:
        value = bpy.data.images.new('TileSource', width=size[0], height=size[1], float_buffer=True)
        color = colors[number] if suffix == 'png' else (number/1000, -.25, 3.5, 1.)
        value.colorspace_settings.name = 'Non-Color'
        value.pixels[:] = list(color)*(size[0]*size[1])
        scene.render.image_settings.file_format = format
        scene.render.image_settings.color_depth = depth
        scene.render.image_settings.color_mode = 'RGBA'
        value.save_render(str(root/f'glaze.{number}.{suffix}'), scene=scene)
        bpy.data.images.remove(value)
for number in [1002, 1011]:
    (root/f'offset.{number}.exr').write_bytes((root/f'glaze.{number}.exr').read_bytes())
for number in [1001,1002,1011]:
    (root/f'alias.{number}.exr').symlink_to(root/f'glaze.{number}.exr')
(root/'broken.1001.exr').write_bytes(b'not an image')
(root/'broken.1002.exr').write_bytes((root/'glaze.1002.exr').read_bytes())
(root/'escape.1001.exr').symlink_to(Path(__file__).resolve())
# A flat emission surface gives a direct four-quadrant UDIM sampling check.
tree = bpy.data.node_groups['ArtistSurface']
texture = tree.nodes['Pattern']
texture.projection, texture.extension = 'FLAT', 'EXTEND'
emission = tree.nodes.new('ShaderNodeEmission')
tree.links.new(texture.outputs['Color'], emission.inputs['Color'])
tree.links.new(emission.outputs['Emission'], next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT').inputs['Shader'])
mesh = bpy.data.meshes.new('TileGrid')
mesh.from_pydata([(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)], [], [(0,1,2,3)])
uv = mesh.uv_layers.new(name='UVMap')
for corner, value in zip(uv.data, [(0,0),(2,0),(2,2),(0,2)], strict=True):
    corner.uv = value
mesh.materials.append(bpy.data.materials['ArtistFinish'])
surface = bpy.data.objects.new('TileGrid', mesh)
scene.collection.objects.link(surface)
for other in list(scene.objects):
    if other != surface:
        bpy.data.objects.remove(other, do_unlink=True)
camera_data = bpy.data.cameras.new('TileCamera')
camera_data.type, camera_data.ortho_scale = 'ORTHO', 2.2
camera = bpy.data.objects.new('TileCamera', camera_data)
scene.collection.objects.link(camera)
camera.location = (0,0,3)
scene.camera = camera
