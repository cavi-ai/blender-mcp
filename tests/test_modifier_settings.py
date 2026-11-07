"""Named modifier edits must reject invalid values before touching the stack."""
import importlib.util
import unittest


class ModifierSettingsTests(unittest.TestCase):
    def planner(self):
        self.assertIsNotNone(importlib.util.find_spec('cavi_blender_mcp.modifier_settings'))
        from cavi_blender_mcp.modifier_settings import update
        return update

    def test_amount_updates_only_the_intended_native_controls(self):
        update=self.planner()
        for kind,settings,amount,expected in [
            ('BEVEL',{'offset_type':'OFFSET'},.02,{'width':.02}),
            ('DECIMATE',{'decimate_type':'COLLAPSE'},.5,{'ratio':.5}),
            ('SUBSURF',{},2,{'levels':2,'render_levels':2}),
            ('REMESH',{'mode':'VOXEL'},.05,{'voxel_size':.05})]:
            with self.subTest(kind=kind):self.assertEqual(update(kind,settings,amount),expected)

    def test_invalid_or_inactive_controls_are_rejected(self):
        update=self.planner()
        for kind,settings,amount in [
            ('BEVEL',{'offset_type':'OFFSET'},0),('BEVEL',{'offset_type':'PERCENT'},.2),
            ('DECIMATE',{'decimate_type':'COLLAPSE'},1.01),('DECIMATE',{'decimate_type':'DISSOLVE'},.5),
            ('SUBSURF',{},1.5),('REMESH',{'mode':'VOXEL'},.001),('REMESH',{'mode':'SMOOTH'},.1),
            ('ARMATURE',{},1),('BEVEL',{'offset_type':'OFFSET'},True),
            ('BEVEL',{'offset_type':'OFFSET'},float('nan'))]:
            with self.subTest(kind=kind,amount=amount),self.assertRaises(ValueError):update(kind,settings,amount)

    def test_stack_budget_covers_both_viewport_and_render_subdivision(self):
        self.planner()
        from cavi_blender_mcp.modifier_settings import stack_bound
        self.assertLess(stack_bound([4]*6,[{'type':'ARMATURE'},
            {'type':'BEVEL','segments':3},{'type':'SUBSURF','levels':1,'render_levels':2}]),500000)
        with self.assertRaises(ValueError):
            stack_bound([4]*10000,[{'type':'SUBSURF','levels':1,'render_levels':3}])
        with self.assertRaises(ValueError):stack_bound([4]*6,[{'type':'NODES'}])
