"""Two procedural hosts in a nested collection definition, outside the scene."""

import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_asset_library import ids

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
before = ids()
runpy.run_path(str(Path(__file__).with_name('procedural_asset_fixture.py')))
kit = bpy.data.collections.new('ProceduralKit')
kit.instance_offset = (.5, -.25, .2)
nested = bpy.data.collections.new('NestedDefinition')
for name, collection in [('Fence', kit), ('OtherFence', nested)]:
    value = bpy.data.objects[name]
    for current in list(value.users_collection):
        current.objects.unlink(value)
    collection.objects.link(value)
placement = bpy.data.objects.new('NestedModule', None)
placement.instance_type, placement.instance_collection = 'COLLECTION', nested
placement.location = (0, 2, 0)
kit.objects.link(placement)
kit.asset_mark()
bpy.data.libraries.write(str(root/'kit.blend'), {kit})
bpy.data.batch_remove(ids=tuple(ids()-before))
bpy.context.view_layer.objects.active = bpy.data.objects['Cube']
bpy.data.objects['Cube'].select_set(True)
