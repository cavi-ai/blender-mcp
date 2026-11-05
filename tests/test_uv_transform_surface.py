"""UV editing is explicit, typed and retains the ownership envelope."""
import asyncio
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from cavi_blender_mcp import server


class UVTransformSurfaceTests(unittest.TestCase):
    def test_face_transform_routes_through_owned_edit(self):
        calls = []
        def call(operation, **params):
            calls.append((operation, params))
            return {}
        with patch.object(server, 'call', call):
            asyncio.run(server.mesh_edit(action='uv_transform', name='Skin', uv_layer='UVMap',
                uv_transform=server.UVTransform(faces=[3,5], offset=(1,0)), lease_id='owner'))
        operation, params = calls[0]
        self.assertEqual(operation, 'transform_uv')
        self.assertEqual(params, {'name':'Skin','uv_layer':'UVMap','lease_id':'owner',
            'transform':{'faces':[3,5],'offset':(1.,0.),'scale':(1.,1.),'rotation_degrees':0.,'pivot':(0.,0.)}})

    def test_model_rejects_empty_float_and_unknown_face_input(self):
        for value in [{'faces':[]}, {'faces':[1.5]}, {'faces':[True]}, {'faces':[-1]},
                      {'faces':[0],'typo':1}, {'faces':[0],'scale':[float('inf'),1]}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                server.UVTransform(**value)

    def test_action_rejects_missing_and_unrelated_parameters(self):
        with self.assertRaises(ValueError):
            asyncio.run(server.mesh_edit(action='uv_transform', name='Skin'))
        with self.assertRaises(ValueError):
            asyncio.run(server.mesh_edit(action='unwrap', name='Skin',
                uv_transform=server.UVTransform(faces=[0])))
