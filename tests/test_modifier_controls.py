"""Native property maps must preserve types and reject clamping or partial edits."""
import unittest


class ModifierControlTests(unittest.TestCase):
    def parser(self):
        from cavi_blender_mcp import modifier_settings
        self.assertTrue(hasattr(modifier_settings,'controls'))
        return modifier_settings.controls

    def schema(self):
        return {'segments':{'type':'INT','min':1,'max':1000,'readonly':False},
            'profile':{'type':'FLOAT','min':0.,'max':1.,'readonly':False},
            'show_render':{'type':'BOOLEAN','readonly':False},
            'offset_type':{'type':'ENUM','items':['OFFSET','PERCENT'],'readonly':False},
            'locked':{'type':'FLOAT','min':0.,'max':1.,'readonly':True}}

    def test_native_types_and_independent_settings_are_retained(self):
        parse=self.parser()
        self.assertEqual(parse({'segments':8,'profile':.73,'show_render':False,'offset_type':'PERCENT'},self.schema()),
            {'segments':8,'profile':.73,'show_render':False,'offset_type':'PERCENT'})

    def test_invalid_maps_fail_before_any_native_assignment(self):
        parse=self.parser()
        for value in ({},{'missing':1},{'segments':True},{'segments':2.5},{'segments':1001},
                {'profile':float('nan')},{'profile':10**500},{'profile':1.01},
                {'show_render':1},{'offset_type':'unknown'},{'locked':.5},{'profile':[.5]},
                {'segments':8,'profile':-1}):
            with self.subTest(value=value),self.assertRaises(ValueError):parse(value,self.schema())
