"""Fixed-size vectors retain their JSON contract without repeated tuple schemas."""

import unittest

from jsonschema import Draft202012Validator
from pydantic import TypeAdapter, ValidationError

from cavi_blender_mcp import server


class VectorSchemaTests(unittest.TestCase):
    def test_homogeneous_vectors_keep_size_and_numeric_acceptance(self):
        for name, size in [('Vector2', 2), ('Vector3', 3), ('RGBA', 4)]:
            adapter = TypeAdapter(getattr(server, name))
            schema = adapter.json_schema()
            original = TypeAdapter(tuple[tuple([server.Number]*size)]).json_schema()
            self.assertNotIn('prefixItems', schema)
            for value in [list(range(size)), [.1]*size, [], [1]*(size-1), [1]*(size+1),
                          [True]*size, ['x']*size, None, {}, 1]:
                self.assertEqual(Draft202012Validator(schema).is_valid(value),
                                 Draft202012Validator(original).is_valid(value))
            self.assertEqual(adapter.validate_python([.1]*size), tuple([.1]*size))
            for value in [[True]*size, [float('nan')]*size]:
                with self.assertRaises(ValidationError):
                    adapter.validate_python(value)
