"""Nested procedural kit with a rig, packed paint and an external float map."""

import hashlib
import json
import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_asset_library import ids

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
runpy.run_path(str(Path(__file__).with_name('asset_library_fixture.py')))
before = ids()
with bpy.data.libraries.load(str(root/'kit.blend'), link=False) as (_, loaded):
    loaded.collections = ['EditableKit']
kit = loaded.collections[0]
kit.instance_offset = (.5, -.25, .2)
fence = next(v for v in kit.objects if v.type == 'MESH' and any(m.type == 'NODES' for m in v.modifiers))
inner = fence.copy()
inner.name = 'InnerFence'
nested = bpy.data.collections.new('InnerModule')
nested.instance_offset = (.1, .2, .3)
nested.objects.link(inner)
placement = bpy.data.objects.new('NestedModule', None)
placement.instance_type, placement.instance_collection = 'COLLECTION', nested
placement.location = (0, 2, 0)
kit.objects.link(placement)
image = bpy.data.images.new('ExternalNormal', width=2, height=2, alpha=True, float_buffer=True)
image.pixels[:] = [.5, .5, 1., 1.]*4
image.colorspace_settings.name = 'Non-Color'
image.filepath_raw, image.file_format, image.use_half_precision = str(root/'normal.exr'), 'OPEN_EXR', True
image.save()
image.source = 'FILE'
material = next(m for m in ids()-before if isinstance(m, bpy.types.Material))
material.node_tree.nodes.new('ShaderNodeTexImage').image = image
bpy.data.libraries.write(str(root/'variant-kit.blend'), {kit}, path_remap='ABSOLUTE')
(root/'variant-expected.json').write_text(json.dumps({
    'external_sha256': hashlib.sha256((root/'normal.exr').read_bytes()).hexdigest()}))
bpy.data.batch_remove(ids=tuple(ids()-before))
