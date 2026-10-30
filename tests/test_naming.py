import unittest

from cavi_blender_mcp.naming import base_name, lint, pair_base, rules

RULES = {"mesh_prefix": "SM_", "lod_suffix": "_LOD{n}",
         "collision_prefixes": ["UCX_", "UBX_", "USP_"]}


class NamingTests(unittest.TestCase):
    def test_roles_and_issues(self):
        self.assertEqual(lint("SM_Rock_LOD2", RULES), {"role": "lod", "lod": 2, "issues": []})
        self.assertEqual(lint("UCX_SM_Rock_00", RULES),
                         {"role": "collision", "base": "SM_Rock", "issues": []})
        self.assertIn("collision_missing_index", lint("UBX_SM_Rock", RULES)["issues"])
        self.assertIn("missing_mesh_prefix", lint("Rock", RULES)["issues"])
        self.assertIn("lod_suffix_format", lint("SM_Rock_lod1", RULES)["issues"])
        self.assertIn("blender_duplicate_suffix", lint("SM_Rock.001", RULES)["issues"])
        self.assertIn("whitespace", lint("SM Rock", RULES)["issues"])
        self.assertEqual(lint("Rock")["issues"], [])

    def test_custom_lod_pattern(self):
        custom = {**RULES, "lod_suffix": "-lod{n}"}
        self.assertEqual(lint("SM_Tree-lod3", custom)["lod"], 3)

    def test_rules_are_validated(self):
        for bad in ({"suffix": "_LOD"}, {"lod_suffix": "_LOD"},
                    {"collision_prefixes": "UCX_"}, {"mesh_prefix": 3}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                rules(bad)

    def test_base_names(self):
        self.assertEqual(base_name("SM_Rock_LOD0"), "SM_Rock")
        self.assertEqual(pair_base("SM_Rock_high"), "SM_Rock")
        self.assertEqual(pair_base("SM_Rock_LOD0_low"), "SM_Rock")
        self.assertEqual(pair_base("SM_Rock_LOW"), "SM_Rock")
