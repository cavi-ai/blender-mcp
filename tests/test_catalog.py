import asyncio
import copy
import unittest
from typing import Annotated

from jsonschema import Draft202012Validator
from pydantic import BaseModel, WithJsonSchema

from cavi_blender_mcp.catalog import BlenderServer, omit_null_defaults


class CatalogTests(unittest.TestCase):
    def test_shared_arrays_preserve_nullable_bounds_and_default_literals(self):
        from cavi_blender_mcp.catalog import shared_arrays, short_references

        vector={'type':['array','null'],'items':{'type':'number'},'minItems':3,'maxItems':3}
        source={'type':'object','additionalProperties':False,'properties':{
            name:{**vector,'description':name,'default':{'$ref':'literal'}} for name in ['head','tail','offset','pivot']}}
        original=copy.deepcopy(source)
        compact=short_references(shared_arrays(source))
        self.assertEqual(source,original)
        self.assertLess(len(str(compact)),len(str(source)))
        for name,field in compact['properties'].items():
            self.assertEqual(field['description'],name)
            self.assertEqual(field['default'],{'$ref':'literal'})
        for value in ({},{'head':None},{'head':[1,2,3]},{'head':[]},{'head':[1,2]},
                      {'head':[1,2,3,4]},{'head':[True,1,2]},{'head':['1',2,3]},
                      {'head':[1,2,3],'foreign':0}):
            self.assertEqual(Draft202012Validator(source).is_valid(value),Draft202012Validator(compact).is_valid(value))
        self.assertEqual(shared_arrays({**source,'$id':'https://example.test/root'}),{**source,'$id':'https://example.test/root'})
        pointer={**source,'$ref':'#/properties/head'}
        self.assertEqual(shared_arrays(pointer),pointer)

    def test_empty_reference_elision_keeps_constraints_and_literal_dictionaries(self):
        from cavi_blender_mcp.catalog import short_references

        ref='#/$defs/Anything'
        source={'$defs':{'Anything':{}},'type':'object','additionalProperties':False,
            'properties':{'payload':{'$ref':ref,'type':'array','minItems':1}},'required':['payload'],
            'default':{'$ref':ref}}
        compact=short_references(source)
        self.assertNotIn('$defs',compact)
        self.assertNotIn('$ref',compact['properties']['payload'])
        self.assertEqual(compact['default'],source['default'])
        self.assertIn('$ref',source['properties']['payload'])
        for value in ({'payload':[1]},{'payload':[]},{'payload':None},{'payload':'bad'},
                      {'payload':[None,{'a':True}]},{},{'payload':[1],'extra':1}):
            self.assertEqual(Draft202012Validator(source).is_valid(value),Draft202012Validator(compact).is_valid(value))
        mapping={'$defs':{'Anything':{}},'type':'object','additionalProperties':{'$ref':ref}}
        self.assertNotIn('additionalProperties',short_references(mapping))
        for value in ({},{'a':[1]},{'b':None},[],None):
            self.assertEqual(Draft202012Validator(mapping).is_valid(value),
                             Draft202012Validator(short_references(mapping)).is_valid(value))
        scoped={**mapping,'unevaluatedProperties':False}
        self.assertEqual(short_references(scoped),scoped)

    def test_named_references_shorten_without_rewriting_literal_data(self):
        from cavi_blender_mcp.catalog import short_references

        pointer = '#/$defs/Long~1RecursiveNode'
        source = {'$defs': {'Long/RecursiveNode': {'anyOf': [
            {'type': 'integer'}, {'type': 'array', 'items': {'$ref': pointer}}]}},
            '$ref': pointer, 'default': {'$ref': pointer}}
        compact = short_references(source)
        self.assertLess(len(compact['$ref']), len(pointer))
        self.assertEqual(compact['default'], {'$ref': pointer})
        self.assertEqual(source['$ref'], pointer)
        for value in (1, [1, [2]], True, 'bad', [None]):
            self.assertEqual(Draft202012Validator(source).is_valid(value),
                             Draft202012Validator(compact).is_valid(value))
        scoped = {**source, '$id': 'https://example.test/schema'}
        self.assertEqual(short_references(scoped), scoped)
        encoded = {'$defs': {'Node': {'type': 'integer'}}, '$ref': '#/$defs/%4Eode'}
        self.assertEqual(short_references(encoded), encoded)

    def test_discovery_omits_default_and_inapplicable_hints_only(self):
        from mcp.types import ToolAnnotations

        server = BlenderServer('hints-fixture', version='1')

        @server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False,
            idempotent_hint=True, open_world_hint=False, title='Read value'))
        def read_value() -> str:
            return 'value'

        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
            idempotent_hint=False, open_world_hint=False))
        def write_value() -> str:
            return 'value'

        @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True))
        def destructive_value() -> str:
            return 'value'

        tools = {t.name: t for t in asyncio.run(server.list_tools())}
        read = tools['read_value'].annotations.model_dump(by_alias=True, exclude_none=True)
        write = tools['write_value'].annotations.model_dump(by_alias=True, exclude_none=True)
        self.assertEqual(read, {'readOnlyHint': True, 'openWorldHint': False, 'title': 'Read value'})
        self.assertEqual(write, {'readOnlyHint': False, 'destructiveHint': False, 'openWorldHint': False})
        # Absent hints retain MCP's documented defaults; explicit nondefaults stay visible.
        self.assertFalse(write.get('readOnlyHint', False))
        self.assertFalse(write.get('idempotentHint', False))
        self.assertFalse(write.get('destructiveHint', True))
        destructive = tools['destructive_value'].annotations.model_dump(by_alias=True, exclude_none=True)
        self.assertIs(destructive['readOnlyHint'], False)
        self.assertIs(destructive['destructiveHint'], True)
        self.assertFalse(destructive.get('readOnlyHint', False))
        self.assertTrue(destructive.get('destructiveHint', True))

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
