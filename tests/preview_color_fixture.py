"""Source display controls deliberately differ from a neutral preview."""

import json
import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.preview_settings import snapshot

runpy.run_path(str(Path(__file__).with_name('material_uv_fixture.py')))
scene = bpy.context.scene
scene.view_settings.view_transform = 'AgX'
scene.view_settings.look = 'None'
scene.view_settings.exposure = 4
scene.view_settings.gamma = 1.8
scene.view_settings.use_curve_mapping = True
if hasattr(scene.view_settings, 'use_white_balance'):
    scene.view_settings.use_white_balance = True
scene.render.use_compositing = True
scene.render.image_settings.file_format = 'OPEN_EXR'
scene.render.image_settings.color_mode = 'RGBA'
scene.render.image_settings.color_depth = '32'


def record_render(scene):
    with (Path(os.environ['CAVI_BLENDER_WORKSPACE']) / 'observed.jsonl').open('a') as stream:
        stream.write(json.dumps(snapshot(scene)) + '\n')


bpy.app.handlers.render_pre.append(record_render)
