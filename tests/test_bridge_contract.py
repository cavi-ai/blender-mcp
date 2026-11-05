import unittest
from unittest.mock import patch

from cavi_blender_mcp.bridge_contract import expected_bridge


class BridgeContractTests(unittest.TestCase):
    def test_digest_identifies_actual_source_and_is_stable(self):
        before=expected_bridge()
        self.assertEqual(before, expected_bridge())
        from pathlib import Path
        read=Path.read_bytes
        for name in ('blender_scene.py', 'skin_projection.py'):
            def changed(path, name=name):
                return read(path)+(b'\n' if path.name==name else b'')
            with self.subTest(name=name), patch.object(Path,'read_bytes',changed):
                self.assertNotEqual(before['build'],expected_bridge()['build'])
