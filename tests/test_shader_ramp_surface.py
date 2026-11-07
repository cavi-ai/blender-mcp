"""Ramp edits use the native settings map without accepting socket-edit fields."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server


class ShaderRampSurfaceTests(unittest.TestCase):
    def test_settings_are_forwarded_in_an_owned_edit(self):
        calls=[]
        def call(operation,params):
            calls.append((operation,params));return {}
        settings={'elements':[{'position':.4,'color':[.1,.2,.3,1]}],'interpolation':'LINEAR'}
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            asyncio.run(server.assign_material(action='set_ramp',material_name='Glaze',node='Palette',
                group_path=['Finish'],node_settings=settings,lease_id='L'))
        self.assertEqual(calls,[('owned_edit',{'operation':'set_shader_ramp','params':{
            'material_name':'Glaze','node':'Palette','group_path':['Finish'],'node_settings':settings,'lease_id':'L'}})])

    def test_missing_and_cross_action_fields_are_rejected_before_dispatch(self):
        with patch.object(server,'BridgeClient') as bridge:
            for options in [{'node':'Palette'}, {'node_settings':{'interpolation':'LINEAR'}},
                            {'node':'Palette','node_settings':{}},
                            {'node':'Palette','node_settings':{'interpolation':'LINEAR'},'outputs':{'Color':[1,1,1,1]}}]:
                with self.subTest(options=options),self.assertRaises(ValueError):
                    asyncio.run(server.assign_material(action='set_ramp',material_name='Glaze',**options))
            bridge.assert_not_called()
