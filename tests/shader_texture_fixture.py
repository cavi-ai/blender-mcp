"""Authored image, scalar and color nodes with high-precision native source files."""

import os
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('shader_input_fixture.py')))
root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
scene = bpy.context.scene
scene.view_settings.view_transform = 'Standard'
for filename, format, depth, color in [
        ('old.png', 'PNG', '16', (.1, .2, .3, 1.)),
        ('finish.png', 'PNG', '16', (.123456, .345678, .567891, 1.)),
        ('finish.tiff', 'TIFF', '16', (.123456, .345678, .567891, 1.)),
        ('finish.exr', 'OPEN_EXR', '32', (.123456, -.25, 3.5, 1.))]:
    source = bpy.data.images.new('Source', width=2, height=2, alpha=True, float_buffer=True)
    source.colorspace_settings.name = 'Non-Color'
    source.pixels[:] = list(color)*4
    scene.render.image_settings.file_format = format
    scene.render.image_settings.color_mode = 'RGBA'
    scene.render.image_settings.color_depth = depth
    source.save_render(str(root/filename), scene=scene)
    bpy.data.images.remove(source)
inner = bpy.data.node_groups['ArtistSurface']
shader = inner.nodes['Hero Surface']
value = inner.nodes.new('ShaderNodeValue')
value.name = 'Glaze Weight'
value.outputs[0].default_value = .2
inner.links.new(value.outputs[0], shader.inputs['Coat Weight'])
tint = inner.nodes.new('ShaderNodeRGB')
tint.name = 'Glow Tint'
inner.links.new(tint.outputs[0], shader.inputs['Emission Color'])
texture = inner.nodes.new('ShaderNodeTexImage')
texture.name = 'Pattern'
texture.interpolation = 'Closest'
texture.projection, texture.projection_blend = 'BOX', .17
texture.extension = 'MIRROR'
texture.label = 'Artist pattern'
image = bpy.data.images.load(str(root/'old.png'))
image.pack()
image.alpha_mode = 'PREMUL'
image['artist_note'] = 'retain'
texture.image = image
inner.links.new(texture.outputs['Color'], shader.inputs['Base Color'])
sibling = inner.nodes.new('ShaderNodeTexImage')
sibling.name, sibling.image = 'Other Pattern', image
