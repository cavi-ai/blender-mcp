import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch


class RuntimeCliTests(unittest.TestCase):
    def test_open_uses_existing_bridge_and_passes_source_pin(self):
        from cavi_blender_mcp.cli import main
        bridge = Mock()
        bridge.call.return_value = {'path': 'scene.blend', 'opened': True}
        output = StringIO()
        with patch('cavi_blender_mcp.cli.BridgeClient', return_value=bridge), redirect_stdout(output):
            result = main(['runtime', 'open', '--project', 'scene.blend', '--lease-id', 'L',
                           '--expected-sha256', 'a' * 64])
        self.assertEqual(result, 0)
        self.assertTrue(json.loads(output.getvalue())['opened'])
        bridge.call.assert_called_once_with('open_project', {'path': 'scene.blend',
            'lease_id': 'L', 'expected_sha256': 'a' * 64})

    def test_open_requires_project_and_lease_before_connecting(self):
        from cavi_blender_mcp.cli import main
        with patch('cavi_blender_mcp.cli.BridgeClient') as bridge:
            for options in ([], ['--project', 'scene.blend'], ['--lease-id', 'L']):
                with self.subTest(options=options), self.assertRaises(SystemExit) as exc:
                    main(['runtime', 'open', *options])
                self.assertEqual(exc.exception.code, 2)
            bridge.assert_not_called()

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
