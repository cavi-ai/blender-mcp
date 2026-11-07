import unittest
from unittest.mock import patch

from cavi_blender_mcp.bridge_contract import expected_bridge


class BridgeContractTests(unittest.TestCase):
    def test_digest_identifies_actual_source_and_is_stable(self):
        before=expected_bridge()
        self.assertEqual(before, expected_bridge())
        from pathlib import Path
        read=Path.read_bytes
        for name in ('blender_scene.py', 'blender_uv_charts.py', 'skin_projection.py', 'preview_settings.py', 'preview_studio.py',
                     'mesh_regions.py', 'uv_regions.py', 'uv_worker.py', 'uv_layout.py', 'process_launch.py',
                     'modifier_settings.py','shader_links.py','native_controls.py'):
                     'uv_density.py', 'mapping.py', 'vertex_edit.py', 'blender_vertices.py'):
            def changed(path, name=name):
                return read(path)+(b'\n' if path.name==name else b'')
            with self.subTest(name=name), patch.object(Path,'read_bytes',changed):
                self.assertNotEqual(before['build'],expected_bridge()['build'])
