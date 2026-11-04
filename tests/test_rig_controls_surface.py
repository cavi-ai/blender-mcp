"""Typed constraints, exact skin weights and editable baked-rig contracts."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp import server
from cavi_blender_mcp.rig_models import IKConstraintSpec


class RigControlsSurfaceTests(unittest.TestCase):
    def test_ik_targets_poles_and_exact_weights_use_the_edit_lease(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'name': 'Rig'}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            constraint = IKConstraintSpec(name='Foot IK', bone='Shin', target='Rig',
                subtarget='FootControl', pole_target='Rig', pole_subtarget='KneeControl',
                pole_angle_degrees=90, chain_count=2)
            asyncio.run(server.rig_edit('constraint', 'Rig', constraint=constraint, lease_id='L'))
            assignment = server.VertexWeights(vertex=3, weights={'Shin': .75, 'Thigh': .25})
            asyncio.run(server.rig_edit('assign_weights', 'Skin', vertex_weights=[assignment],
                                       lease_id='L'))
        self.assertEqual(calls[0][0], 'owned_edit')
        self.assertEqual(calls[0][1]['operation'], 'add_constraint')
        self.assertEqual(calls[0][1]['params']['constraint']['pole_angle_degrees'], 90)
        self.assertEqual(calls[1][1]['operation'], 'assign_weights')
        self.assertEqual(calls[1][1]['params']['vertex_weights'],
                         [{'vertex':3, 'weights':{'Shin':.75, 'Thigh':.25}}])
        self.assertFalse(calls[1][1]['params']['normalize'])
        self.assertTrue(all(c[1]['params']['lease_id']=='L' for c in calls))

    def test_bake_declares_the_clean_export_copy_and_sampling_range(self):
        calls=[]
        def call(operation, params):
            calls.append(params)
            return {'name':'Rig_Baked'}
        with patch.object(server,'BridgeClient',return_value=SimpleNamespace(call=call)):
            asyncio.run(server.rig_edit('bake','Rig',new_name='Rig_Baked',
                action_name='Walk_Baked',start_frame=1,end_frame=24,frame_step=1,
                names=['Skin'],skinning_mode='linear',lease_id='L'))
        self.assertEqual(calls[0]['operation'],'bake_rig')
        self.assertEqual(calls[0]['params']['end_frame'],24)
        self.assertEqual(calls[0]['params']['skinning_mode'],'linear')
