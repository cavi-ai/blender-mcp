import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cavi_blender_mcp.blender_errors import PreflightRejected
from cavi_blender_mcp.source_identity import LoadedSource


class OpenProjectTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name).resolve()
        self.current = self.root / 'current.blend'
        self.target = self.root / 'target.blend'
        self.current.write_bytes(b'current')
        self.target.write_bytes(b'target')
        self.loaded = LoadedSource()
        self.loaded.capture(self.current)
        self.data = SimpleNamespace(filepath=str(self.current), is_dirty=False)

        def load(**kwargs):
            self.data.filepath = kwargs['filepath']
            self.loaded.capture(self.data.filepath)
            return {'FINISHED'}

        self.loader = Mock(side_effect=load)
        bpy = SimpleNamespace(data=self.data, ops=SimpleNamespace(wm=SimpleNamespace(
            open_mainfile=self.loader)))
        self.stub = patch.dict(sys.modules, bpy=bpy)
        self.stub.start()
        self.addCleanup(self.stub.stop)

    def open(self, **params):
        from cavi_blender_mcp.blender_project import open_project
        return open_project({'path': 'target.blend', **params}, self.root, self.loaded,
                            lambda: self.data.filepath)

    def test_load_pins_source_and_disables_layout_and_scripts(self):
        digest = hashlib.sha256(b'target').hexdigest()
        result = self.open(expected_sha256=digest)
        self.assertEqual(result, {'path': str(self.target), 'sha256': digest, 'bytes': 6,
                                 'project_id': str(self.target), 'opened': True})
        self.loader.assert_called_once_with(filepath=str(self.target), load_ui=False,
                                            use_scripts=False)
        self.assertFalse(self.loaded.inspect(self.target, False)['dirty'])

    def test_refusals_leave_current_project_untouched(self):
        for params in ({'path': '../outside.blend'}, {'path': 'missing.blend'},
                       {'path': ''}, {'expected_sha256': '0' * 64},
                       {'expected_sha256': 'bad'}, {'force': True}):
            with self.subTest(params=params), self.assertRaises(PreflightRejected):
                self.open(**params)
        self.loader.assert_not_called()
        self.assertEqual(self.data.filepath, str(self.current))

    def test_symlink_cannot_escape_workspace(self):
        with tempfile.TemporaryDirectory() as other:
            external = Path(other) / 'external.blend'
            external.write_bytes(b'external')
            (self.root / 'link.blend').symlink_to(external)
            with self.assertRaises(PreflightRejected):
                self.open(path='link.blend')
        self.loader.assert_not_called()

    def test_dirty_and_unidentified_current_sources_are_preserved(self):
        self.data.is_dirty = True
        with self.assertRaisesRegex(PreflightRejected, 'Unsaved'):
            self.open()
        self.data.is_dirty = False
        self.loaded.mark_changed()
        with self.assertRaisesRegex(PreflightRejected, 'Unsaved'):
            self.open()
        self.loaded.capture(self.current)
        self.current.write_bytes(b'replaced')
        with self.assertRaisesRegex(PreflightRejected, 'changed on disk'):
            self.open()
        self.loaded.source = None
        with self.assertRaisesRegex(PreflightRejected, 'identity'):
            self.open()
        self.loader.assert_not_called()

    def test_same_clean_source_is_a_noop(self):
        result = self.open(path='current.blend')
        self.assertFalse(result['opened'])
        self.loader.assert_not_called()

    def test_native_failure_and_changed_source_are_not_preflight_rejections(self):
        def changed(**kwargs):
            self.target.write_bytes(b'changed during load')
            self.data.filepath = kwargs['filepath']
            self.loaded.capture(self.target)
            return {'FINISHED'}
        for outcome in ({'CANCELLED'}, RuntimeError('native failed'), changed):
            self.loader.side_effect = outcome if callable(outcome) or isinstance(outcome, Exception) else None
            self.loader.return_value = outcome
            self.data.filepath = str(self.current)
            self.loaded.capture(self.current)
            self.target.write_bytes(b'target')
            with self.subTest(outcome=outcome), self.assertRaises(RuntimeError):
                self.open()


class OpenSurfaceTests(unittest.TestCase):
    def test_owned_routing_and_timeout(self):
        import asyncio

        from cavi_blender_mcp import server
        from cavi_blender_mcp.client import operation_timeout
        from cavi_blender_mcp.operations import LEASE_FREE, SLOW_TIMEOUT
        bridge = Mock(return_value={'path': 'target.blend'})
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=bridge)):
            asyncio.run(server.asset_io('open', 'target.blend', expected_sha256='a' * 64,
                                         lease_id='L'))
            bridge.assert_called_once_with('owned_edit', {'operation': 'open_project',
                'params': {'lease_id': 'L', 'path': 'target.blend', 'expected_sha256': 'a' * 64}})
            bridge.reset_mock()
            for args in ({'action': 'save', 'expected_sha256': 'a' * 64},
                         {'action': 'open', 'names': ['Cube']}):
                with self.assertRaisesRegex(ValueError, 'does not accept'):
                    asyncio.run(server.asset_io(path='target.blend', **args))
            bridge.assert_not_called()
        self.assertNotIn('open_project', LEASE_FREE)
        self.assertEqual(operation_timeout('owned_edit', {'operation': 'open_project'}), SLOW_TIMEOUT)
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == 'asset_io')
        self.assertTrue(tool.annotations.destructive_hint)
