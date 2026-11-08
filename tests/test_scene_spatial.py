"""Spatial queries preserve units, reject ambiguous selections and bound intermediate work."""
import asyncio
import importlib.util
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from jsonschema import Draft202012Validator

from cavi_blender_mcp import scene_models, server


class SceneSpatialTests(unittest.TestCase):
    def model(self, **changes):
        model = getattr(scene_models, 'SpatialQuery', None)
        self.assertIsNotNone(model, 'Read-only scene spatial query is missing')
        return model.model_validate({'subjects': ['Shelter'], 'context': ['Town'], **changes})

    def helpers(self):
        name = 'cavi_blender_mcp.spatial_query'
        self.assertIsNotNone(importlib.util.find_spec(name), 'Bounded spatial helpers are missing')
        return __import__(name, fromlist=['validate'])

    def test_selection_rejects_duplicates_shared_objects_and_unknown_options(self):
        for changes in ({'subjects': []}, {'subjects': ['Shelter', 'Shelter']},
                        {'context': ['Shelter']}, {'context': ['Town', 'Town']},
                        {'subjects': ['A'] * 33}, {'all_clear': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.model(**changes)

    def test_proposed_delta_requires_a_finite_invertible_affine_matrix(self):
        identity = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        self.model(proposed_world_delta=identity)
        for matrix in ([[1, 0]], [[0] * 4] * 4,
                       [[True, 0, 0, 0], *identity[1:]],
                       [[float('inf'), 0, 0, 0], *identity[1:]],
                       [*identity[:3], [0, 0, .1, 1]]):
            with self.subTest(matrix=matrix), self.assertRaises(ValueError):
                self.model(proposed_world_delta=matrix)

    def test_finite_translation_outside_native_float32_range_rejects_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, 'float32'):
            self.model(proposed_world_delta=[[1, 0, 0, 1e300], [0, 1, 0, 0],
                                             [0, 0, 1, 0], [0, 0, 0, 1]])
        with self.assertRaisesRegex(ValueError, 'float32'):
            self.helpers().transformed([(2e38, 0, 0)],
                [[2, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])

    def coplanar(self, a, b):
        function = getattr(self.helpers(), 'coplanar_overlap', None)
        self.assertIsNotNone(function, 'Coplanar triangle narrowphase is missing')
        return function(a, b)

    def test_contained_coplanar_triangle_counts_as_overlap_with_opposite_winding(self):
        a = ((0., 0., 1.), (2., 0., 1.), (0., 2., 1.))
        b = ((.25, .25, 1.), (.25, .5, 1.), (.5, .25, 1.))
        self.assertTrue(self.coplanar(a, b))
        self.assertTrue(self.coplanar(b, a))

    def test_shared_coplanar_edge_and_vertex_are_contacts(self):
        a = ((0., 0., 0.), (2., 0., 0.), (0., 2., 0.))
        for b in (((2., 0., 0.), (2., 2., 0.), (0., 2., 0.)),
                  ((2., 0., 0.), (3., 0., 0.), (2., -1., 0.))):
            with self.subTest(b=b):
                self.assertTrue(self.coplanar(a, b))

    def test_coplanar_triangles_with_overlapping_aabbs_can_have_separated_surfaces(self):
        a = ((0., 0., 0.), (2., 0., 0.), (0., 2., 0.))
        b = ((1.5, 1.5, 0.), (3., 1.5, 0.), (1.5, 3., 0.))
        self.assertFalse(self.coplanar(a, b))

    def test_coplanar_projection_handles_a_tilted_plane_and_rejects_parallel_offset(self):
        a = ((0., 0., 0.), (2., 0., 2.), (0., 2., 0.))
        b = ((.25, .25, .25), (.5, .25, .5), (.25, .5, .25))
        self.assertTrue(self.coplanar(a, b))
        self.assertFalse(self.coplanar(a, tuple((x, y, z + .01) for x, y, z in b)))

    def test_numeric_budgets_reject_boolean_nonfinite_and_excessive_values(self):
        for changes in ({'samples_per_side': True}, {'max_triangles': 200001},
                        {'max_pair_tests': 2000001}, {'max_results': 257},
                        {'min_clearance_m': float('nan')}, {'min_clearance_m': -1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.model(**changes)

    def test_metre_world_delta_rotates_and_translates_without_changing_input(self):
        helpers = self.helpers()
        points = [(2., 3., 4.)]
        moved = helpers.transformed(points, [[0, -1, 0, 10], [1, 0, 0, -2],
                                            [0, 0, -2, 5], [0, 0, 0, 1]])
        self.assertEqual(moved, [(7., 0., -3.)])
        self.assertEqual(points, [(2., 3., 4.)])

    def test_spatial_chunks_retain_all_triangles_and_limit_native_overlap_size(self):
        helpers = self.helpers()
        triangles = [((i * 3., 0., 0.), (i * 3. + 1, 0., 0.),
                      (i * 3., 1., 0.)) for i in range(300)]
        chunks = helpers.chunks(triangles)
        self.assertEqual(sorted(i for chunk in chunks for i in chunk['indices']), list(range(300)))
        self.assertLessEqual(max(len(chunk['indices']) for chunk in chunks), 128)
        self.assertLessEqual(max(len(a['indices']) * len(b['indices'])
                                 for a in chunks for b in chunks), 16384)

    def test_pair_budget_refuses_incomplete_overlap_work_instead_of_reporting_no_hit(self):
        helpers = self.helpers()
        triangles = [((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))] * 5
        a, b = helpers.chunks(triangles), helpers.chunks(triangles)
        with self.assertRaisesRegex(ValueError, 'pair budget'):
            list(helpers.chunk_pairs(a, b, 24))
        self.assertEqual(len(list(helpers.chunk_pairs(a, b, 25))), 1)

    def test_samples_are_bounded_and_include_surface_interiors(self):
        helpers = self.helpers()
        triangles = [((0., 0., 0.), (3., 0., 0.), (0., 3., 0.))]
        samples = helpers.samples(triangles, 4)
        self.assertEqual([point for _, point in samples],
                         [(0., 0., 0.), (3., 0., 0.), (0., 3., 0.), (1., 1., 0.)])
        self.assertEqual(len(helpers.samples(triangles * 1000, 7)), 7)

    def test_spatial_selector_routes_without_a_lease_and_excludes_other_modes(self):
        query = self.model()
        tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == 'scene_info')
        self.assertTrue(Draft202012Validator(tool.input_schema).is_valid(
            {'spatial': ['Shelter', 'Town']}), 'Public subject/context pair is missing')
        calls = []
        def call(operation, params):
            calls.append((operation, params))
            return {'scope': 'scene_spatial_inspection', 'spatial': {}}
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=call)):
            asyncio.run(server.scene_info(spatial=('Shelter', 'Town')))
            for other in ({'name': 'Shelter'}, {'limit': 1}, {'faces': True},
                          {'surface_ray': scene_models.SurfaceRay(origin_world=(0, 0, 0),
                              direction_world=(0, 0, 1), max_distance_m=10)}):
                with self.subTest(other=other), self.assertRaises(ValueError):
                    asyncio.run(server.scene_info(spatial=('Shelter', 'Town'), **other))
        self.assertEqual(calls, [('inspect_scene_spatial', query.model_dump(mode='json'))])
        from cavi_blender_mcp.operations import LEASE_FREE
        self.assertIn('inspect_scene_spatial', LEASE_FREE)

    def test_public_spatial_selector_rejects_objects_tuning_and_wrong_pair_lengths(self):
        def forbidden(*_):
            raise AssertionError('Invalid public spatial input reached the native bridge')
        with patch.object(server, 'BridgeClient', return_value=SimpleNamespace(call=forbidden)):
            for value in (['Shelter'], ['Shelter', 'Town', 'Extra'], ['', 'Town'],
                          {'subjects': ['Shelter'], 'context': ['Town']},
                          {'subjects': ['Shelter'], 'context': ['Town'], 'max_triangles': 10}):
                with self.subTest(value=value), self.assertRaisesRegex(Exception, 'validation'):
                    asyncio.run(server.mcp.call_tool('scene_info', {'spatial': value}))
