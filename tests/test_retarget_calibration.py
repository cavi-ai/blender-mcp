"""Calibrated motion and declared contact windows have explicit contracts."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.rig_models import ContactWindow, RetargetCalibration


class CalibrationTests(unittest.TestCase):
    def test_calibration_routes_only_to_retarget(self):
        calls=[]
        def call(operation,params):
            calls.append(params);return {'name':'Target'}
        calibration=RetargetCalibration(root='Root',root_translation_scale=1.2)
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            asyncio.run(server.rig_edit('retarget','Target',source='Source',source_action='Walk',action_name='NewWalk',calibration=calibration,lease_id='L'))
            with self.assertRaisesRegex(ValueError,'does not accept: calibration'):
                asyncio.run(server.rig_edit('clear_pose','Target',calibration=calibration,lease_id='L'))
        self.assertEqual(calls[0]['params']['calibration']['root_translation_scale'],1.2)
        self.assertEqual(calls[0]['params']['calibration']['alignment_degrees'],(0,0,0))

    def test_contacts_are_forwarded_to_read_only_inspection(self):
        calls=[]
        def call(operation,params):
            calls.append((operation,params));return {'armature':'Target','bones':[],'meshes':[]}
        contact=ContactWindow(bone='Foot.L',point=(0,0,0),start_frame=1,end_frame=10,max_drift_m=.01,max_height_error_m=.02,ground_z_m=0)
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            asyncio.run(server.inspect_rig('Target',['Skin'],action='Walk',contacts=[contact]))
        self.assertEqual(calls[0][0],'inspect_rig')
        self.assertEqual(calls[0][1]['contacts'][0]['bone'],'Foot.L')

    def test_profiles_reject_invalid_numbers_and_windows(self):
        for fields in ({'root_translation_scale':0},{'root_translation_scale':float('nan')},{'alignment_degrees':[0,1]},{'unknown':True}):
            with self.assertRaises(ValueError):RetargetCalibration(root='Root',**fields)
        with self.assertRaises(ValueError):ContactWindow(bone='Foot',point=(0,0,0),start_frame=9,end_frame=1,max_drift_m=.01,max_height_error_m=.01,ground_z_m=0)
