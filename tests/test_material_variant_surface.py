"""Authored material variants keep existing surface controls and ownership."""
import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server


class MaterialVariantSurfaceTests(unittest.TestCase):
    def test_copy_routes_with_object_bindings_by_default(self):
        calls=[]
        def call(operation, **params):
            calls.append((operation,params))
            return {}
        with patch.object(server,'call',call):
            asyncio.run(server.assign_material(action='make_unique',names=['Body'],
                material_name='Blue Finish',lease_id='author'))
        self.assertEqual(calls,[('make_material_unique',{'material_name':'Blue Finish',
            'names':['Body'],'slot':0,'link_mode':'OBJECT','lease_id':'author'})])

    def test_copy_accepts_explicit_data_binding(self):
        with patch.object(server,'call',return_value={}) as call:
            asyncio.run(server.assign_material(action='make_unique',names=['Body'],
                material_name='Blue Finish',slot=1,link_mode='DATA',lease_id='author'))
        self.assertEqual(call.call_args.kwargs['link_mode'],'DATA')
        self.assertEqual(call.call_args.kwargs['slot'],1)

    def test_copy_rejects_missing_targets_and_unrelated_controls(self):
        for options in [{},{'names':['Body'],'roughness':.5},
                        {'names':['Body'],'node':'Surface'},{'names':['Body'],'instance':'Kit'}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                asyncio.run(server.assign_material(action='make_unique',material_name='Blue Finish',**options))
