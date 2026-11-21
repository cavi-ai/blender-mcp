"""Post-load import budgets stay on the GLB preflight figures."""

import unittest
from pathlib import Path

from cavi_blender_mcp.importing import (
    MAX_ANIMATIONS,
    MAX_JOINTS,
    MAX_MORPH_TARGETS,
    MAX_SKINNED_MESHES,
    MAX_SKINS,
    MAX_TOTAL_JOINTS,
    MAX_TOTAL_MORPH_TARGETS,
    check_imported_actions,
    check_imported_armatures,
    check_imported_bones,
    check_imported_morph_targets,
    check_imported_shape_key_actions,
    check_imported_shape_keys,
    check_imported_skinned_meshes,
    check_imported_vertex_groups,
)

BRIDGE = Path(__file__).resolve().parents[1] / "src/cavi_blender_mcp/blender_bridge.py"

FIGURES = (
    ("MAX_SKINS", MAX_SKINS, 16),
    ("MAX_JOINTS", MAX_JOINTS, 512),
    ("MAX_TOTAL_JOINTS", MAX_TOTAL_JOINTS, 1024),
    ("MAX_SKINNED_MESHES", MAX_SKINNED_MESHES, 64),
    ("MAX_ANIMATIONS", MAX_ANIMATIONS, 32),
    ("MAX_MORPH_TARGETS", MAX_MORPH_TARGETS, 64),
    ("MAX_TOTAL_MORPH_TARGETS", MAX_TOTAL_MORPH_TARGETS, 256),
)

SINGLE = (
    (check_imported_armatures, MAX_SKINS, "Imported armatures exceed the import budget"),
    (check_imported_vertex_groups, MAX_JOINTS, "Imported skins exceed the vertex-group budget"),
    (check_imported_skinned_meshes, MAX_SKINNED_MESHES,
     "Imported skinned meshes exceed the import budget"),
    (check_imported_actions, MAX_ANIMATIONS, "Imported actions exceed the import budget"),
    (check_imported_shape_keys, MAX_MORPH_TARGETS, "Imported shape keys exceed the import budget"),
    (check_imported_morph_targets, MAX_TOTAL_MORPH_TARGETS,
     "Imported morph targets exceed the import budget"),
    (check_imported_shape_key_actions, MAX_ANIMATIONS,
     "Imported shape-key actions exceed the import budget"),
)

CALLS = (
    "check_imported_armatures(",
    "check_imported_bones(",
    "check_imported_vertex_groups(",
    "check_imported_skinned_meshes(",
    "check_imported_actions(",
    "check_imported_shape_keys(",
    "check_imported_morph_targets(",
    "check_imported_shape_key_actions(",
)

STALE = (
    "len(armatures) > 16",
    "bones > 1024",
    "len(item.data.bones) > 512",
    "len(item.vertex_groups) > 512",
    "len(skinned) > 64",
    "len(actions) > 32",
    "if count > 64",
    "morph_targets > 256",
    "len(shape_key_animations) > 32",
)


class ImportBudgetTests(unittest.TestCase):
    def test_shared_figures(self):
        for name, value, expected in FIGURES:
            with self.subTest(name=name):
                self.assertEqual(value, expected)

    def test_at_budget_is_kept_and_over_budget_raises_the_existing_message(self):
        for check, limit, message in SINGLE:
            with self.subTest(check=check.__name__):
                check(limit)
                with self.assertRaises(RuntimeError) as caught:
                    check(limit + 1)
                self.assertEqual(str(caught.exception), message)
        check_imported_bones(MAX_TOTAL_JOINTS, [MAX_JOINTS])
        for total, counts in (
            (MAX_TOTAL_JOINTS + 1, [1]),
            (MAX_JOINTS + 1, [MAX_JOINTS + 1]),
        ):
            with self.subTest(total=total, counts=counts):
                with self.assertRaises(RuntimeError) as caught:
                    check_imported_bones(total, counts)
                self.assertEqual(str(caught.exception), "Imported bones exceed the import budget")

    def test_post_load_uses_the_shared_checks(self):
        text = BRIDGE.read_text()
        for call in CALLS:
            with self.subTest(call=call):
                self.assertIn(call, text)
        for stale in STALE:
            with self.subTest(stale=stale):
                self.assertNotIn(stale, text)
        self.assertIn("len(objects) > 1000", text)
        self.assertIn('previous["materials"]) > 64', text)
        self.assertIn('previous["images"]) > 64', text)
        self.assertIn("> 16 * 1024 * 1024", text)


if __name__ == "__main__":
    unittest.main()
