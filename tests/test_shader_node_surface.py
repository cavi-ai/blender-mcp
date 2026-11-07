"""Native shader node discovery and creation keep argument and lease boundaries."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShaderNodeSurfaceTests(unittest.TestCase):
    def test_uv_identifiers_remain_strings_with_native_byte_bounds(self):
        from cavi_blender_mcp.native_controls import controls

        schema={'uv_map':{'type':'STRING','readonly':False,'max_length':8}}
        self.assertEqual(controls({'uv_map':'BakeUV'},schema,subject='shader node',parameter='node_settings'),{'uv_map':'BakeUV'})
        for value in (False,3,None,{},'bad\0name','longer-than-eight','é'*5):
            with self.subTest(value=value),self.assertRaises(ValueError):
                controls({'uv_map':value},schema,subject='shader node',parameter='node_settings')

    def test_discovery_is_lease_free_and_creation_uses_owned_edit(self):
        calls=[]
        def call(operation,params):
            calls.append((operation,params))
            return {}
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(action='node_types',material_name='Glaze',
                node_type='ShaderNodeMath',group_path=['Finish']))
            asyncio.run(server.assign_material(action='create_node',material_name='Glaze',
                node='WearMultiply',node_type='ShaderNodeMath',node_settings={'operation':'MULTIPLY'},
                group_path=['Finish'],lease_id='L'))
        self.assertEqual(calls[0],('inspect_shader_node_types',{'material_name':'Glaze',
            'group_path':['Finish'],'node_type':'ShaderNodeMath','offset':0,'limit':100}))
        self.assertEqual(calls[1],('owned_edit',{'operation':'create_shader_node','params':{
            'material_name':'Glaze','node':'WearMultiply','node_type':'ShaderNodeMath',
            'node_settings':{'operation':'MULTIPLY'},'group_path':['Finish'],'lease_id':'L'}}))

    def test_node_arguments_cannot_leak_to_other_actions(self):
        with patch.object(server,'BridgeClient') as bridge:
            for args in [{'action': 'create_node','node': 'New'},{'action': 'create_node','node_type': 'ShaderNodeMath'},
                         {'action': 'inspect','node_type': 'ShaderNodeMath'},
                         {'action': 'node_types','node': 'Existing'},
                         {'action': 'node_types','node_settings': {'operation':'MULTIPLY'}},
                         {'action': 'create_node','node': 'New','node_type': 'ShaderNodeMath','inputs': {'Value':1}}]:
                with self.subTest(args=args),self.assertRaises(ValueError):
                    asyncio.run(server.assign_material(material_name='Glaze',**args))
            bridge.assert_not_called()
