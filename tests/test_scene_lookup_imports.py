"""Scene lookup is imported beside the bridge, not through it."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "cavi_blender_mcp"
FEATURES = ("blender_export.py", "blender_geometry.py", "blender_rigging.py")


class SceneLookupImportTests(unittest.TestCase):
    def test_feature_modules_do_not_import_lookup_from_the_bridge(self):
        for name in FEATURES:
            text = (ROOT / name).read_text()
            with self.subTest(name=name):
                self.assertNotIn("from .blender_bridge import", text)
                self.assertIn("from .blender_lookup import", text)

    def test_lookup_module_does_not_import_the_bridge(self):
        self.assertNotIn("blender_bridge", (ROOT / "blender_lookup.py").read_text())
