"""Named UV export has a distinct bridge operation and explicit receipt metadata."""
import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server


class ExportUvSurfaceTests(unittest.TestCase):
    def test_named_uv_routes_to_updated_bridge_even_without_other_options(self):
        with patch.object(server,'call',return_value={}) as call:
            asyncio.run(server.asset_io('export','hero.fbx',names=['Hero'],uv_layer='Atlas',lease_id='owner'))
        self.assertEqual(call.call_args.args,('export_uv_asset',))
        self.assertEqual(call.call_args.kwargs['uv_layer'],'Atlas')
        self.assertEqual(call.call_args.kwargs['lease_id'],'owner')

    def test_named_uv_on_evaluated_assemblies_uses_its_own_operation(self):
        with patch.object(server,'call',return_value={}) as call:
            asyncio.run(server.asset_io('export','kit.glb',names=['Kit'],assembly=True,uv_layer='Atlas'))
        self.assertEqual(call.call_args.args,('export_uv_assembly',))
        self.assertEqual(call.call_args.kwargs['uv_layer'],'Atlas')

    def test_uv_layer_is_not_silently_accepted_by_other_actions(self):
        for action,path,args in [('save','scene.blend',{}),('import','hero.fbx',{'name':'Loaded'}),
                                 ('export','pair.fbx',{'bake_pair':server.BakePair(low=['Low'],high=['High'])})]:
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'does not accept: uv_layer'):
                asyncio.run(server.asset_io(action,path,uv_layer='Atlas',**args))
