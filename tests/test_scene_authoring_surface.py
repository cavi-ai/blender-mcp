import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

from cavi_blender_mcp import server


class SceneAuthoringTests(unittest.TestCase):
    def test_production_render_keeps_resolution_precision_and_budget(self):
        calls=[]
        def call(operation, params):
            calls.append((operation,params))
            return {'path':'hero.png'}
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            profile=server.RenderSpec(path='hero.png',camera='Hero',width=6000,height=3000,
                                      max_pixels=18000000,samples=256)
            asyncio.run(server.scene_edit('render',render=profile,lease_id='L'))
        params=calls[0][1]['params'];self.assertEqual(params['definition']['bit_depth'],'16')
        self.assertEqual(params['definition']['width'],6000)
        self.assertEqual(calls[0][0],'owned_edit')
        self.assertEqual(params['lease_id'],'L')

    def test_invalid_precision_or_pixel_budget_is_rejected_before_render(self):
        for values in ({'width':6000,'height':3000}, {'file_format':'png','bit_depth':'32'}):
            with self.subTest(values=values),self.assertRaises(ValidationError):
                server.RenderSpec(path='hero.png',camera='Hero',**values)
