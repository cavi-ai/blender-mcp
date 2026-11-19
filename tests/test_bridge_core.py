"""Blender's Python loads the server's installed MCP Core, not a copy."""
import subprocess
import sys
import unittest
from pathlib import Path

import cavi_mcp_core

SRC = Path(__file__).resolve().parents[1] / "src"
PROBE = ("import sys; sys.path.insert(0, sys.argv[1]); "
         "from cavi_blender_mcp import importing; print(importing.core_workspace.__file__)")


class BridgeCoreTests(unittest.TestCase):
    def test_bridge_without_site_packages_uses_the_installed_core(self):
        result = subprocess.run([sys.executable, "-I", "-S", "-c", PROBE, str(SRC)],
                                capture_output=True, text=True, timeout=60, check=True)
        self.assertEqual(Path(result.stdout.strip()).resolve(),
                         (Path(cavi_mcp_core.__file__).parent / "workspace.py").resolve())


if __name__ == "__main__":
    unittest.main()
