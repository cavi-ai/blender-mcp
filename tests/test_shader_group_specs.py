"""Group blueprints reject malformed declarations before native allocation."""
import unittest

from cavi_blender_mcp.blender_shader_group_specs import blueprint


class ShaderGroupSpecTests(unittest.TestCase):
    def test_preserves_declared_defaults_precision_and_repeated_labels(self):
        rows=[{'name':'Signal','in_out':'INPUT','socket_type':'NodeSocketFloat',
            'default_value':-.123456789,'min_value':-4,'max_value':4},
            {'name':'Signal','in_out':'OUTPUT','socket_type':'NodeSocketFloat'}]
        value={'name':'StudioFunction','interface':rows}
        self.assertEqual(blueprint(value),value)
        self.assertEqual(blueprint({'name':'Empty'}),{'name':'Empty','interface':[]})

    def test_invalid_structure_directions_ranges_and_unknown_fields_are_rejected(self):
        row={'name':'Value','in_out':'INPUT','socket_type':'NodeSocketFloat'}
        for value in [None,{}, {'name':False}, {'name':'bad\0name'}, {'name':'A','extra':1},
            {'name':'A','interface':[{}]},
            {'name':'A','interface':[{**row,'in_out':'BOTH'}]},
            {'name':'A','interface':[{**row,'socket_type':True}]},
            {'name':'A','interface':[{**row,'min_value':True}]},
            {'name':'A','interface':[{**row,'max_value':float('inf')}]},
            {'name':'A','interface':[{**row,'min_value':10**500}]},
            {'name':'A','interface':[{**row,'min_value':2,'max_value':1}]},
            {'name':'A','interface':[{**row,'default':0}]}]:
            with self.subTest(value=value),self.assertRaises(ValueError):blueprint(value)
        with self.assertRaises(TypeError):blueprint({'name':'A','interface':{}})
