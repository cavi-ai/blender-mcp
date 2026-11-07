"""Shader rewiring uses explicit socket bindings and native edit ownership."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShaderLinkSurfaceTests(unittest.TestCase):
    def test_native_conversions_preserve_color_to_emission(self):
        from cavi_blender_mcp.shader_links import compatible

        for source,target in [('RGBA','SHADER'),('VECTOR','VALUE'),('VALUE','RGBA'),('SHADER','SHADER'),('BUNDLE','BUNDLE')]:
            self.assertTrue(compatible(source,target))
        for source,target in [('SHADER','RGBA'),('SHADER','VALUE'),('MENU','VALUE'),('RGBA','CLOSURE')]:
            self.assertFalse(compatible(source,target))

    def test_connect_and_disconnect_forward_exact_bindings_with_ownership(self):
        calls=[]
        def call(operation, params):
            calls.append((operation,params))
            return {}
        binding={'Color':{'node':'Tint','socket':'Color'}}
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            for action in ['connect','disconnect']:
                asyncio.run(server.assign_material(action=action,material_name='Glaze',node='Surface',
                    group_path=['Finish'],inputs=binding,lease_id='L',
                    **({'update_existing':True} if action=='connect' else {})))
        for action,(operation,envelope) in zip(['connect','disconnect'],calls,strict=True):
            self.assertEqual(operation,'owned_edit')
            self.assertEqual(envelope['operation'],'edit_material_links')
            self.assertEqual(envelope['params'],{'material_name':'Glaze','node':'Surface',
                'group_path':['Finish'],'inputs':binding,'lease_id':'L','action':action,
                'update_existing':action=='connect'})

    def test_malformed_or_cross_action_arguments_never_reach_native(self):
        invalid=[{}, {'Color':.5}, {'Color':{'node':'Tint'}},
            {'Color':{'node':'Tint','socket':'Color','extra':True}},
            {'':{'node':'Tint','socket':'Color'}}, {'Color':{'node':'','socket':'Color'}},
            {'Color':{'node':False,'socket':'Color'}}, {'Color':{'node':'Tint','socket':''}}]
        with patch.object(server,'BridgeClient') as bridge:
            for inputs in invalid:
                with self.subTest(inputs=inputs),self.assertRaises(ValueError):
                    asyncio.run(server.assign_material(action='connect',material_name='Glaze',node='Surface',inputs=inputs))
            for options in [{'outputs':{'Value':1}}, {'roughness':.2}, {'image':{}},
                            {'action':'disconnect','update_existing':True}]:
                with self.subTest(options=options),self.assertRaises((ValueError,AttributeError)):
                    asyncio.run(server.assign_material(**{'action':'connect','material_name':'Glaze',
                        'node':'Surface','inputs':{'Color':{'node':'Tint','socket':'Color'}},**options}))
            bridge.assert_not_called()
