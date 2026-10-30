import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class RuntimeCliTests(unittest.TestCase):
    def test_offline_status_is_json_with_failure_exit(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, CAVI_BLENDER_CONNECTION=str(Path(folder) / "absent.json"))
            result = subprocess.run(
                [sys.executable, "-m", "cavi_blender_mcp.cli", "runtime", "status"],
                env=env, capture_output=True, text=True, timeout=5, check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["connected"])
        self.assertNotIn("Traceback", result.stderr)

    def test_unknown_command_fails_without_starting_stdio(self):
        result = subprocess.run(
            [sys.executable, "-m", "cavi_blender_mcp.cli", "runtime", "unknown"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_background_is_only_for_start(self):
        result = subprocess.run(
            [sys.executable, "-m", "cavi_blender_mcp.cli", "runtime", "status", "--background"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--background", result.stderr)
