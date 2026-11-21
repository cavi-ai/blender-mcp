"""Dispatched clip and shape-key mutations stay on the default timeout."""

import unittest

from cavi_blender_mcp.client import operation_timeout
from cavi_blender_mcp.operations import (
    DEFAULT_TIMEOUT,
    LEASE_FREE,
    LONG_OPERATIONS,
    OPERATIONS,
    SLOW_OPERATIONS,
    SOURCE_PRESERVING,
)


class OperationCatalogTests(unittest.TestCase):
    def test_clip_and_shape_key_operations_use_the_default_timeout(self):
        names = (
            'set_action', 'rename_action', 'delete_action', 'nla_push', 'nla_edit',
            'nla_remove', 'shape_key_add', 'shape_key_value', 'shape_key_remove',
            'shape_key_keyframe',
        )
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, OPERATIONS)
                self.assertNotIn(name, LEASE_FREE)
                self.assertNotIn(name, SOURCE_PRESERVING)
                self.assertNotIn(name, SLOW_OPERATIONS)
                self.assertNotIn(name, LONG_OPERATIONS)
                self.assertEqual(operation_timeout('owned_edit', {'operation': name}),
                                 DEFAULT_TIMEOUT)
