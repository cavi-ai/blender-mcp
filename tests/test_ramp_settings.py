"""Ramp requests retain native precision and reject invalid batches before writes."""
import unittest

from cavi_blender_mcp.blender_ramp_settings import equivalent, settings


class RampSettingsTests(unittest.TestCase):
    def test_native_float_comparison_keeps_small_edits_and_ignores_storage_rounding(self):
        self.assertTrue(equivalent({'color':[.1]}, {'color':[.10000000149011612]}))
        self.assertFalse(equivalent({'color':[0]}, {'color':[1e-9]}))
        self.assertFalse(equivalent([1], [.9999999]))

    def schema(self):
        return {'min_elements':1,'max_elements':32,'position':{'min':0,'max':1},
            'color':{'min':0,'max':3.4e38},'controls':{
                'interpolation':{'type':'ENUM','items':['LINEAR','CONSTANT'],'readonly':False}}}

    def test_sorted_elements_keep_single_stop_hdr_and_alpha(self):
        row={'position':.4,'color':[2.5,.25,.125,.4]}
        self.assertEqual(settings({'elements':[row]},self.schema()),{'elements':[row]})
        other={'position':.1,'color':[0,0,0,1]}
        self.assertEqual(settings({'elements':[row,other]},self.schema())['elements'],[other,row])
        self.assertEqual(settings({'elements':[row,row]},self.schema())['elements'],[row,row])

    def test_invalid_or_incomplete_stops_and_enums_are_rejected(self):
        good={'position':0,'color':[0,0,0,1]}
        for value in [{},{'unknown':1},{'interpolation':'bad'}, {'elements':[]},
                      {'elements':[good]*33},{'elements':[{'position':False,'color':[0,0,0,1]}]},
                      {'elements':[{'position':1.1,'color':[0,0,0,1]}]},
                      {'elements':[{'position':0,'color':[0,0,0]}]},
                      {'elements':[{'position':0,'color':[float('nan'),0,0,1]}]},
                      {'elements':[{'position':0,'color':[10**500,0,0,1]}]},
                      {'elements':[{'position':0,'color':[False,0,0,1]}]},
                      {'elements':[{'position':0,'color':[-.1,0,0,1]}]},
                      {'elements':[{**good,'extra':1}]}]:
            with self.subTest(value=value),self.assertRaises(ValueError):settings(value,self.schema())
