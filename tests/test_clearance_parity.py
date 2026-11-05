"""Repeated native facet hits do not change parity or bypass contact and query limits."""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np


def parity_kernel():
    path = Path(__file__).resolve().parents[1] / 'src/cavi_blender_mcp/blender_clearance.py'

    class ArrayVector(np.ndarray):
        def __new__(cls, value):
            return np.asarray(value, dtype=float).view(cls)

        def normalized(self):
            return self / np.linalg.norm(self)

    # Only the import-time Blender dependencies are stubbed; the parity loop and budget are real.
    stubs = {'bpy': SimpleNamespace(), 'mathutils': SimpleNamespace(Vector=ArrayVector),
             'mathutils.bvhtree': SimpleNamespace(BVHTree=None),
             'cavi_blender_mcp.blender_mesh_sample': SimpleNamespace(snapshot=None),
             'cavi_blender_mcp.blender_motion_compare': SimpleNamespace(set_frame=None)}
    spec = importlib.util.spec_from_file_location('cavi_blender_mcp._parity_test', path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module


class TraceTree:
    def __init__(self, rays):
        self.rays, self.offsets, self.calls = rays, [0, 0, 0], 0

    def ray_cast(self, origin, direction, _length):
        self.calls += 1
        ray = int(np.argmax(np.abs(direction)))
        offset = self.offsets[ray]
        self.offsets[ray] += 1
        if offset == len(self.rays[ray]):
            return None, None, None, None
        face, distance = self.rays[ray][offset]
        return origin + direction * distance, None, face, distance


class ClearanceParityTests(unittest.TestCase):
    kernel = parity_kernel()

    def classify(self, tree, maximum=100):
        budget = self.kernel.Budget(maximum)
        point = self.kernel.DIRECTIONS[0].copy() * 0
        result = self.kernel.inside_component(point, (tree, np.full(3, -1.), np.ones(3)), budget)
        return result, budget

    def test_captured_repeated_facet_counts_only_two_crossings(self):
        tree = TraceTree([[], [(319, .09276621043682098), (319, 1.3790222510579042e-6),
                              (380, .010207048617303371)], []])
        result, budget = self.classify(tree)
        self.assertIs(result, False)
        self.assertEqual((tree.calls, budget.used), (6, 7))

    def test_repeated_facet_near_contact_is_not_a_new_contact(self):
        result, _ = self.classify(TraceTree([[], [(9, .1), (9, self.kernel.EPSILON / 8),
                                                (12, .2)], []]))
        self.assertIs(result, False)

    def test_first_contact_and_distinct_nearby_facet_remain_ambiguous(self):
        for hits in [[(9, self.kernel.EPSILON / 8)],
                     [(9, .1), (12, self.kernel.EPSILON / 8)]]:
            with self.subTest(hits=hits):
                self.assertIsNone(self.classify(TraceTree([hits, [], []]))[0])

    def test_repeated_facet_exhaustion_keeps_the_query_limit(self):
        class EndlessTree:
            calls = 0

            def ray_cast(self, origin, direction, _length):
                self.calls += 1
                return origin + direction * .01, None, 9, .01

        tree, budget = EndlessTree(), self.kernel.Budget(6)
        with self.assertRaises(self.kernel.QueryBudgetReached):
            self.kernel.inside_component(self.kernel.DIRECTIONS[0].copy() * 0,
                (tree, np.full(3, -1.), np.ones(3)), budget)
        self.assertEqual((tree.calls, budget.used), (5, 6))

    def test_repeated_facet_without_progress_remains_ambiguous(self):
        class StalledTree:
            calls = 0
            hit = None

            def ray_cast(self, origin, direction, _length):
                self.calls += 1
                if self.hit is None:
                    self.hit = origin + direction * .01
                return self.hit, None, 9, .01 if self.calls == 1 else 0.

        tree = StalledTree()
        self.assertIsNone(self.classify(tree)[0])
        self.assertEqual(tree.calls, 2)
