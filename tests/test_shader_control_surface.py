"""Existing shader controls use owned edits and retain strict argument boundaries."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShaderControlSurfaceTests(unittest.TestCase):
    def test_existing_controls_are_forwarded_with_ownership(self):
        calls=[]
        def call(operation,params):
            calls.append((operation,params));return {}
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(action='set_node',material_name='Glaze',node='Noise',
                group_path=['Finish'],node_settings={'noise_dimensions':'4D','normalize':True},lease_id='L'))
        self.assertEqual(calls,[('owned_edit',{'operation':'set_shader_node','params':{
            'material_name':'Glaze','node':'Noise','group_path':['Finish'],
            'node_settings':{'noise_dimensions':'4D','normalize':True},'lease_id':'L'}})])

    def test_missing_empty_and_cross_action_fields_reject_before_dispatch(self):
        for args in [{'node':'Noise'},{'node_settings':{'normalize':True}},
            {'node':'Noise','node_settings':{}},
            {'node':'Noise','node_settings':{'normalize':True},'node_type':'ShaderNodeTexNoise'},
            {'node':'Noise','node_settings':{'normalize':True},'inputs':{'Scale':1}}]:
            with self.subTest(args=args),patch.object(server,'BridgeClient') as bridge,self.assertRaises(ValueError):
                asyncio.run(server.assign_material(action='set_node',material_name='Glaze',**args))
            bridge.assert_not_called()
