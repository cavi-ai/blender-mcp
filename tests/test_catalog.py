import asyncio
import unittest

from cavi_blender_mcp.catalog import BlenderServer, omit_null_defaults


class CatalogTests(unittest.TestCase):
    def test_compaction_preserves_constraints_and_non_null_defaults(self):
        source = {'type': 'object', 'required': ['gamma'], 'additionalProperties': False, 'properties': {
            'gamma': {'type': 'number', 'exclusiveMinimum': 0, 'default': 1},
            'optional': {'anyOf': [{'type': 'string'}, {'type': 'null'}], 'default': None},
            'flag': {'type': 'boolean', 'default': False}, 'zero': {'type': 'number', 'default': 0},
            'empty': {'type': 'string', 'default': ''}, 'null': {'const': None}, 'choice': {'enum': [None, 'a']}}}
        expected = {'type': 'object', 'required': ['gamma'], 'additionalProperties': False, 'properties': {
            'gamma': {'type': 'number', 'exclusiveMinimum': 0, 'default': 1},
            'optional': {'anyOf': [{'type': 'string'}, {'type': 'null'}]},
            'flag': {'type': 'boolean', 'default': False}, 'zero': {'type': 'number', 'default': 0},
            'empty': {'type': 'string', 'default': ''}, 'null': {'const': None}, 'choice': {'enum': [None, 'a']}}}
        self.assertEqual(omit_null_defaults(source), expected)
        self.assertIn('default', source['properties']['optional'])

    def test_discovery_omits_only_optional_null_default_annotations(self):
        for compact in (True, False):
            with self.subTest(compact=compact):
                server = BlenderServer('fixture', version='1', compact=compact)

                @server.tool()
                def inspect_value(value: str | None = None) -> str:
                    return value or 'empty'

                tool = asyncio.run(server.list_tools())[0]
                field = tool.input_schema['properties']['value']
                self.assertEqual('default' in field, not compact)
                self.assertNotIn('value', tool.input_schema.get('required', []))
