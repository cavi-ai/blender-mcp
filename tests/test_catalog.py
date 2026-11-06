import asyncio
import unittest
from typing import Annotated

from jsonschema import Draft202012Validator
from pydantic import BaseModel, WithJsonSchema

from cavi_blender_mcp.catalog import BlenderServer, omit_null_defaults


class CatalogTests(unittest.TestCase):
    def test_discovery_preserves_literal_default_fields_in_output_constraints(self):
        class Receipt(BaseModel):
            payload: Annotated[dict, WithJsonSchema({'type': 'object', 'const': {'default': None}})]

        server = BlenderServer('literal-fixture', version='1')

        @server.tool()
        async def literal() -> Receipt:
            return {'payload': {'default': None}}

        async def exercise():
            schema = (await server.list_tools())[0].output_schema
            result = await server.call_tool('literal', {})
            Draft202012Validator(schema).validate(result.structured_content)

        asyncio.run(exercise())

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
        compact = omit_null_defaults(source)
        for value in [{'gamma': 1}, {'gamma': 0}, {'gamma': True}, {'gamma': 1, 'optional': None},
                      {'gamma': 1, 'optional': 'x'}, {'gamma': 1, 'flag': False, 'zero': 0},
                      {'gamma': 1, 'empty': '', 'null': None, 'choice': None},
                      {'gamma': 1, 'choice': 'wrong'}, {'gamma': 1, 'foreign': 1}]:
            self.assertEqual(Draft202012Validator(expected).is_valid(value),
                             Draft202012Validator(compact).is_valid(value))
        for name in ['gamma', 'flag', 'zero', 'empty']:
            self.assertEqual(compact['properties'][name]['default'],
                             source['properties'][name]['default'])
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
