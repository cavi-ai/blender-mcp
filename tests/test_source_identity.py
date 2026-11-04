import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from cavi_blender_mcp.source_identity import LoadedSource


class SourceIdentityTests(unittest.TestCase):
    def test_same_size_disk_replacement_does_not_relabel_loaded_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'source.blend'
            path.write_bytes(b'original')
            loaded = LoadedSource()
            loaded.capture(path)
            original = loaded.inspect(path, False)
            path.write_bytes(b'replaced')
            self.assertEqual(loaded.inspect(path, False), original)
            self.assertNotEqual(original['saved_source']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            loaded.capture(path)
            self.assertEqual(loaded.inspect(path, True)['saved_source']['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertTrue(loaded.inspect(path, True)['dirty'])
            self.assertIsNone(loaded.inspect(Path(directory)/'other.blend', False)['saved_source'])

    @unittest.skipUnless(os.environ.get('CAVI_SOURCE_IDENTITY_NATIVE') == '1', 'dedicated native bridge opt-in')
    def test_native_save_and_external_replacement_keep_distinct_source_identity(self):
        import asyncio
        import sys
        import uuid

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def run():
            if not os.environ.get('CAVI_BLENDER_CONNECTION') or not os.environ.get('CAVI_BLENDER_WORKSPACE'):
                raise ValueError('Set an explicit dedicated bridge and workspace')
            root = Path(os.environ['CAVI_BLENDER_WORKSPACE']).resolve()
            target = root / ('source-identity-' + uuid.uuid4().hex + '.blend')
            params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=dict(os.environ))
            async with stdio_client(params) as (r,w), ClientSession(r,w) as session:
                await session.initialize()
                async def call(name, **args):
                    result = await session.call_tool(name, args)
                    self.assertFalse(result.is_error, result)
                    return result.structured_content
                status = await call('session_control', action='inspect')
                claim = await call('session_control', action='claim', owner='source-identity-native-test', expected_project=status['project_id'])
                try:
                    await call('asset_io', action='save', path=target.name, lease_id=claim['lease_id'])
                    source = (await call('scene_info', limit=1))['source_state']
                    raw = target.read_bytes()
                    self.assertFalse(source['dirty'])
                    self.assertEqual(source['saved_source']['sha256'], hashlib.sha256(raw).hexdigest())
                    try:
                        target.write_bytes(raw + b'external-replacement')
                        stale = (await call('scene_info', limit=1))['source_state']
                        self.assertEqual(source, stale)
                        self.assertNotEqual(stale['saved_source']['sha256'], hashlib.sha256(target.read_bytes()).hexdigest())
                    finally:
                        target.write_bytes(raw)
                finally:
                    await call('session_control', action='release', lease_id=claim['lease_id'])
        asyncio.run(run())
