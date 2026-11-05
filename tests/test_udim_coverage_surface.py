"""Coverage keeps read-only dispatch and distinguishes UV result contracts."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cavi_mcp_core.schema import compact_schema
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from cavi_blender_mcp import server
from cavi_blender_mcp.contracts import UVLayout


class CoverageSurfaceTests(unittest.TestCase):
    def test_coverage_is_lease_free(self):
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.inspect_uv_layout(names=['Body'], udim_image='Skin', material='Finish'))
        self.assertEqual(calls, [('inspect_udim_coverage', {'names':['Body'], 'udim_image':'Skin',
            'material':'Finish', 'uv_layer':None, 'comparison_budget':None})])

    def test_modes_reject_ineffective_or_missing_parameters(self):
        for options in [{}, {'udim_image':'Skin','texture_resolution':(1024,1024)},
                        {'udim_image':'Skin','padding_pixels':2}]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                asyncio.run(server.inspect_uv_layout(names=['Body'], **options))

    def test_scope_selects_required_response_fields_without_wrappers(self):
        shared = {'material':None, 'objects':[], 'not_checked':[], 'complete':True}
        old = {**shared, 'scope':'source_uv_one_texture_set', 'unique_tile_ready':True,
               'texture_resolution':[1024,1024], 'overlap':{}, 'padding':{}}
        new = {**shared, 'scope':'source_uv_udim_coverage', 'coverage':{'passed':False,'missing_tiles':[1012]}}
        schemas = [UVLayout.model_json_schema(), compact_schema(UVLayout.model_json_schema(), output=True)]
        for record in [old,new]:
            self.assertEqual(UVLayout.model_validate(record).model_dump(mode='json'), record)
            for schema in schemas:
                Draft202012Validator(schema).validate(record)
        bad = [{**old,'scope':new['scope']}, {**new,'scope':old['scope']},
               {k:v for k,v in old.items() if k != 'padding'},
               {k:v for k,v in new.items() if k != 'coverage'}]
        for record in bad:
            with self.subTest(record=record), self.assertRaises(ValidationError):
                UVLayout.model_validate(record)
            for schema in schemas:
                self.assertFalse(Draft202012Validator(schema).is_valid(record))
