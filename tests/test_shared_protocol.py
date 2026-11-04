"""Shared schema semantics and pinned vendor identity."""
import copy
import hashlib
import json
import unittest
from pathlib import Path

from cavi_blender_mcp._vendor.schema import compact_schema, validate_variant


class SharedProtocolTests(unittest.TestCase):
    def test_compaction_preserves_literals_bounds_and_input_schema(self):
        schema={'title':'Wrapper','properties':{
            'value':{'title':'Value','anyOf':[{'type':'number','minimum':0},{'type':'null'}]},
            'literal':{'const':{'title':'User data'}},
            'count':{'anyOf':[{'type':'integer'},{'type':'number'}],'default':2}}}
        original=copy.deepcopy(schema)
        result=compact_schema(schema,output=True)
        self.assertEqual(result['properties']['value'],{'type':['number','null'],'minimum':0})
        self.assertEqual(result['properties']['literal'],{'const':{'title':'User data'}})
        self.assertEqual(result['properties']['count'],{'type':'number'})
        self.assertEqual(schema,original)
        with self.assertRaises(ValueError):
            validate_variant({'name':None},{'name'},(('name',),),set())

    def test_vendor_bytes_match_pinned_source_hash(self):
        root=Path(__file__).resolve().parents[1]/'src/cavi_blender_mcp/_vendor'
        origin=json.loads((root/'schema.origin.json').read_text())
        self.assertEqual(hashlib.sha256((root/'schema.py').read_bytes()).hexdigest(),origin['sha256'])
