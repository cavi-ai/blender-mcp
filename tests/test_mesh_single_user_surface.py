"""Mesh ownership can change without applying object transforms."""
import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server


class MeshSingleUserSurfaceTests(unittest.TestCase):
    def test_object_action_routes_without_transform_parameters(self):
        calls=[]
        def call(operation, **params):
            calls.append((operation,params))
            return {}
        with patch.object(server,'call',call):
            asyncio.run(server.object_edit(action='make_single_user',name='Skin',lease_id='author'))
        self.assertEqual(calls,[('make_mesh_single_user',{'name':'Skin','lease_id':'author'})])

    def test_unrelated_parameters_are_rejected(self):
        with self.assertRaises(ValueError):
            asyncio.run(server.object_edit(action='make_single_user',name='Skin',components=['scale']))
