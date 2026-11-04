"""Write an editable kit library and leave a separate consuming scene with collisions."""

import hashlib
import json
import os
import runpy
from pathlib import Path

import bpy

from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_node_inputs import InputStore

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
original = ids()
runpy.run_path(str(Path(__file__).with_name('procedural_asset_fixture.py')))
kit = bpy.data.collections.new('EditableKit')
bpy.context.scene.collection.children.link(kit)
fence = bpy.data.objects['Fence']
for collection in list(fence.users_collection):
    collection.objects.unlink(fence)
kit.objects.link(fence)
tree = fence.modifiers[0].node_group
finish = next(s.identifier for s in tree.interface.items_tree if s.name == 'Finish')
InputStore(fence.modifiers[0])[finish] = bpy.data.materials['Blue']
image = bpy.data.images.new('PackedPaint', width=2, height=2, alpha=True, float_buffer=True)
image.pixels[:] = [.05, .2, .8, 1]*4
image.pack()
material = bpy.data.materials['Blue']
node = material.node_tree.nodes.new('ShaderNodeTexImage')
node.image = image
material.node_tree.links.new(node.outputs['Color'], material.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
rig = bpy.data.objects.new('LibraryRig', bpy.data.armatures.new('LibraryRig'))
kit.objects.link(rig)
for value in list(bpy.context.selected_objects):
    value.select_set(False)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode='EDIT')
bone = rig.data.edit_bones.new('Root')
bone.head, bone.tail = (0, 0, 0), (0, 0, 1)
bpy.ops.object.mode_set(mode='OBJECT')
rig.pose.bones['Root'].rotation_mode = 'XYZ'
for frame, angle in [(1, 0), (6, .2), (11, 0)]:
    rig.pose.bones['Root'].rotation_euler.z = angle
    rig.pose.bones['Root'].keyframe_insert('rotation_euler', frame=frame)
rig.animation_data.action.name = 'LibraryIdle'
mesh = bpy.data.meshes.new('LibrarySkin')
mesh.from_pydata([(-1,-1,0), (1,-1,0), (1,1,0), (-1,1,0), (-1,-1,1), (1,-1,1), (1,1,1), (-1,1,1)],
                 [], [(0,3,2,1), (4,5,6,7), (0,1,5,4), (1,2,6,5), (2,3,7,6), (3,0,4,7)])
skin = bpy.data.objects.new('LibrarySkin', mesh)
kit.objects.link(skin)
skin.vertex_groups.new(name='Root').add(list(range(8)), 1., 'REPLACE')
skin.modifiers.new('Skin', 'ARMATURE').object = rig
skin.parent = rig
kit.asset_mark()
tree.asset_mark()
expected = {'packed_sha256': hashlib.sha256(image.packed_file.data).hexdigest()}
bpy.data.libraries.write(str(root/'kit.blend'), {kit, material, tree})
# A source with a missing image exercises removal of all partially appended IDs.
bad = bpy.data.materials.new('BrokenFinish')
bad.use_nodes = True
missing = bpy.data.images.new('MissingPaint', width=2, height=2)
missing.source = 'FILE'
missing.filepath = str(root.parent/'missing-library-fixture-image.png')
bad.node_tree.nodes.new('ShaderNodeTexImage').image = missing
bpy.data.libraries.write(str(root/'broken.blend'), {bad})
bpy.data.batch_remove(ids=tuple(ids()-original))
sentinel = bpy.data.objects['Cube']
sentinel.name = 'Fence'
sentinel.select_set(True)
bpy.context.view_layer.objects.active = sentinel
bpy.context.scene.frame_set(12, subframe=.5)
bpy.data.materials.new('Blue')
(root/'expected.json').write_text(json.dumps(expected))
