import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


class UVWorkerTests(unittest.TestCase):
    def test_worker_is_headless_and_cleans_bound_input_and_output(self):
        from cavi_blender_mcp.uv_worker import solve

        def run(command, **kwargs):
            self.assertIn('--background', command)
            self.assertIn('--disable-autoexec', command)
            self.assertTrue(kwargs['start_new_session'])
            self.assertEqual(kwargs['timeout'], 45)
            self.assertNotIn('CAVI_BLENDER_CONNECTION', kwargs['env'])
            self.assertNotIn('PYTHONPATH', kwargs['env'])
            payload = Path(command[-2]).read_bytes()
            Path(command[-1]).write_text(json.dumps({'input_sha256': hashlib.sha256(payload).hexdigest(), 'uv': []}))
            return SimpleNamespace(returncode=0)

        with tempfile.TemporaryDirectory() as directory:
            with patch('subprocess.run', side_effect=run), patch.dict(os.environ,
                    {'CAVI_BLENDER_CONNECTION': 'shared.json', 'PYTHONPATH': 'server-abi'}):
                self.assertEqual(solve('blender', directory, {'vertices': []})['uv'], [])
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_timeout_failure_and_wrong_response_do_not_retain_scratch_files(self):
        from cavi_blender_mcp.uv_worker import solve

        def wrong(command, **kwargs):
            Path(command[-1]).write_text(json.dumps({'input_sha256': '0'*64}))
            return SimpleNamespace(returncode=0)

        for failure in (subprocess.TimeoutExpired('blender', 45), FileNotFoundError('blender'), wrong):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                with patch('subprocess.run', side_effect=failure), self.assertRaises(ValueError):
                    solve('blender', directory, {})
                self.assertEqual(list(Path(directory).iterdir()), [])
