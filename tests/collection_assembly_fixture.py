"""A nested environment kit with shared meshes, generated geometry and nonzero pivots."""

import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_node_inputs import InputStore

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
before = ids()
runpy.run_path(str(Path(__file__).with_name('procedural_asset_fixture.py')))
kit = bpy.data.collections.new('GardenKit')
kit.instance_offset = (.5, -.25, .2)
fence = bpy.data.objects['Fence']
for collection in list(fence.users_collection):
    collection.objects.unlink(fence)
kit.objects.link(fence)
tree = fence.modifiers[0].node_group
finish = next(s.identifier for s in tree.interface.items_tree if s.name == 'Finish')
InputStore(fence.modifiers[0])[finish] = bpy.data.materials['Blue']
mesh = bpy.data.objects['Cube'].data.copy()
mesh.materials.clear()
mesh.materials.append(bpy.data.materials['Blue'])
base = bpy.data.objects.new('BaseStone', mesh)
kit.objects.link(base)
base.location, base.scale = (0, 1, -.3), (1.6, .3, .2)
details = bpy.data.collections.new('TrimDefinition')
details.instance_offset = (.1, .2, .3)
trim = bpy.data.objects.new('TrimStone', mesh)
details.objects.link(trim)
trim.location, trim.scale = (.7, .2, .5), (.2, .1, .3)
nested = bpy.data.objects.new('NestedTrim', None)
kit.objects.link(nested)
nested.instance_type, nested.instance_collection = 'COLLECTION', details
nested.location = (1, .4, 0)
nested.rotation_euler.z = .2
kit.asset_mark()
bpy.data.libraries.write(str(root/'kit.blend'), {kit})
bpy.data.batch_remove(ids=tuple(ids()-before))
bpy.context.view_layer.objects.active = bpy.data.objects['Cube']
bpy.data.objects['Cube'].select_set(True)
