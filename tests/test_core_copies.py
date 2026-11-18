"""Blender's Python runs byte-identical copies of MCP Core's standard-library path modules."""
import unittest
from pathlib import Path

from cavi_mcp_core import files, workspace

import cavi_blender_mcp

PACKAGE = Path(cavi_blender_mcp.__file__).parent


class CoreCopyTests(unittest.TestCase):
    def test_bridge_copies_match_the_installed_core(self):
        for name, module in (("core_workspace.py", workspace), ("core_files.py", files)):
            with self.subTest(name=name):
                self.assertEqual((PACKAGE / name).read_bytes(), Path(module.__file__).read_bytes(),
                                 f"{name} differs from MCP Core; copy {module.__file__} again")


if __name__ == "__main__":
    unittest.main()
