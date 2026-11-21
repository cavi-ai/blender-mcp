import unittest

from cavi_blender_mcp.rig_dispatch import RIG_EDIT

EXPECTED = {
    "add_constraint": ("blender_rig_controls", "HANDLERS"),
    "remove_constraint": ("blender_rig_controls", "HANDLERS"),
    "assign_weights": ("blender_rig_controls", "HANDLERS"),
    "transfer_skin_weights": ("blender_skin_transfer", "transfer"),
    "bake_rig": ("blender_rig_bake", "bake"),
    "set_action": ("blender_nla", "HANDLERS"),
    "rename_action": ("blender_nla", "HANDLERS"),
    "delete_action": ("blender_nla", "HANDLERS"),
    "nla_push": ("blender_nla", "HANDLERS"),
    "nla_edit": ("blender_nla", "HANDLERS"),
    "nla_remove": ("blender_nla", "HANDLERS"),
    "retarget_rig": ("blender_retarget", "retarget"),
    "lock_rig_contacts": ("blender_foot_locks", "lock_contacts"),
    "pose_rig": ("blender_animation", "HANDLERS"),
    "keyframe_rig": ("blender_animation", "HANDLERS"),
    "clear_pose": ("blender_animation", "HANDLERS"),
    "create_armature": ("blender_rigging", "HANDLERS"),
    "bind_skin": ("blender_rigging", "HANDLERS"),
    "repair_weights": ("blender_rigging", "HANDLERS"),
    "edit_armature": ("blender_rigging", "HANDLERS"),
    "add_metarig": ("blender_rigify", "HANDLERS"),
    "generate_rigify": ("blender_rigify", "HANDLERS"),
}


class RigDispatchTests(unittest.TestCase):
    def test_operation_set_and_targets_match_the_table(self):
        self.assertEqual(set(RIG_EDIT), set(EXPECTED))
        self.assertEqual(RIG_EDIT, EXPECTED)
