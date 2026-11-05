"""Shader-channel bakes have explicit source sockets and format-aware precision."""
import asyncio
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from cavi_blender_mcp import server


class ShaderBakeSurfaceTests(unittest.TestCase):
    def source(self):
        return server.ShaderBakeSource(material='Finish',group_path=['Controls'],node='Pattern',socket='Color')

    def test_exr_defaults_to_float32_and_keeps_the_owned_call(self):
        with patch.object(server,'call',return_value={}) as call:
            asyncio.run(server.bake(map='shader',name='Body',path='color.exr',source=self.source(),lease_id='owner'))
        self.assertEqual(call.call_args.args,('bake_shader',))
        self.assertEqual(call.call_args.kwargs['bit_depth'],32)
        self.assertEqual(call.call_args.kwargs['source']['socket'],'Color')
        self.assertEqual(call.call_args.kwargs['lease_id'],'owner')

    def test_png_defaults_to_16_and_other_modes_keep_their_precision(self):
        with patch.object(server,'call',return_value={}) as call:
            asyncio.run(server.bake(map='shader',name='Body',path='mask.png',source=self.source()))
            self.assertEqual(call.call_args.kwargs['bit_depth'],16)
            asyncio.run(server.bake(map='normal',name='Body',path='normal.png'))
            self.assertEqual(call.call_args.kwargs['bit_depth'],16)

    def test_shader_source_is_required_and_geometry_projection_is_rejected(self):
        for options in [{},{'source':self.source(),'high':['High']},
                        {'source':self.source(),'normal_space':'tangent'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                asyncio.run(server.bake(map='shader',name='Body',path='mask.png',**options))
        with self.assertRaises(ValueError):
            asyncio.run(server.bake(map='ao',name='Body',path='ao.png',source=self.source()))

    def test_source_is_typed_and_refuses_unknown_or_empty_fields(self):
        for value in [{'material':'Finish','node':'','socket':'Color'},
                      {'material':'Finish','node':'Pattern','socket':'Color','role':'beauty'},
                      {'material':'Finish','node':'Pattern','socket':'Color','code':'run()'}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                server.ShaderBakeSource(**value)
