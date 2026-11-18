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


class RuntimeToolTests(unittest.TestCase):
    def test_session_control_reports_and_restarts_the_bridge(self):
        import asyncio

        from mcp.server.mcpserver.exceptions import ToolError

        from cavi_blender_mcp import server
        from cavi_blender_mcp.bridge_contract import expected_bridge
        calls, generation = [], [1]

        def call(operation, params):
            calls.append((operation, params))
            if operation == 'runtime_restart':
                generation[0] += 1
            return {'connected': True, 'pid': 7, 'generation': generation[0], 'version': '5.2.3',
                    'bridge': expected_bridge(), 'file': '', 'workspace': '/w', 'object_count': 0,
                    'dirty': False, 'background': True}

        with patch.object(server, 'BridgeClient', return_value=Mock(call=call)):
            status = asyncio.run(server.mcp.call_tool('session_control', {'action': 'status'}))
            restart = asyncio.run(server.mcp.call_tool('session_control',
                                                       {'action': 'restart', 'lease_id': 'L'}))
            for arguments in ({'action': 'status', 'lease_id': 'L'}, {'action': 'restart'},
                              {'action': 'status', 'owner': 'me'}):
                with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                    asyncio.run(server.mcp.call_tool('session_control', arguments))
        self.assertEqual(calls, [('runtime_status', {}), ('runtime_restart', {'lease_id': 'L'}),
                                 ('runtime_status', {})])
        status, restart = status.structured_content, restart.structured_content
        self.assertTrue(status['bridge_compatibility']['matches'])
        self.assertEqual((restart['generation'], restart['restarted']), (2, True))


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
