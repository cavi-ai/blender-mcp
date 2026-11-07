"""Mirrored edits retain existing asymmetry and reject uncertain matches."""
import unittest

from cavi_blender_mcp import vertex_edit


class VertexSymmetryTests(unittest.TestCase):
    def plan(self, points, seeds, offset, **options):
        function = getattr(vertex_edit, 'symmetric_offsets', None)
        self.assertIsNotNone(function, 'Symmetric vertex planning is missing')
        return function(points, options.pop('edges', []), seeds, offset,
            options.pop('axis', 'X'), options.pop('tolerance_m', .001), **options)

    def test_mirrored_displacements_keep_existing_asymmetry_and_center_plane(self):
        points = [(-1,0,0), (1.0001,0,0), (0,0,0)]
        offsets, report, weights = self.plan(points, [0,2], [.2,.1,.3])
        self.assertEqual(offsets, {0:(.2,.1,.3),1:(-.2,.1,.3),2:(0.,.1,.3)})
        self.assertEqual(report['pairs'], [[0,1],[2,2]])
        self.assertEqual(weights, {0:1.,1:1.,2:1.})

    def test_proportional_influence_stays_on_source_side_then_reflects(self):
        points = [(-1,0,0),(0,0,0),(1,0,0),(-1,1,0),(1,1,0)]
        offsets, report, weights = self.plan(points,[0],[.25,0,.5],radius=.05,
            edges=[(0,1),(1,2),(0,3),(2,4)],linear=((2,0,0),(0,3,0),(0,0,1)),unit_m=.01)
        self.assertEqual(set(offsets),{0,1,2,3,4})
        for index,want in [(0,1),(1,.648),(2,1),(3,.352),(4,.352)]:
            self.assertAlmostEqual(weights[index],want)
        self.assertAlmostEqual(offsets[2][0],-.25)
        self.assertEqual(offsets[1][0],0)
        self.assertEqual(report['source_side'],-1)

    def test_world_metric_controls_matching_under_scale_and_shear(self):
        points=[(-1,0,0),(1,.0004,0)]
        self.plan(points,[0],[0,0,.1],linear=((2,4,0),(0,3,0),(0,0,1)),unit_m=.01)
        with self.assertRaises(ValueError):
            self.plan(points,[0],[0,0,.1],linear=((2,4,0),(0,3,0),(0,0,1)),unit_m=1)

    def test_missing_ambiguous_nonreciprocal_and_mixed_sides_reject(self):
        for points,seeds in [([(-1,0,0)],[0]),
                ([(-1,0,0),(1,0,0),(1,0,0)],[0]),
                ([(-1,0,0),(-1,.0001,0),(1,0,0)],[0]),
                ([(-1,0,0),(1,0,0)],[0,1])]:
            with self.subTest(points=points), self.assertRaises(ValueError):
                self.plan(points,seeds,[.1,0,0])

    def test_combined_affected_budget_and_invalid_metric_reject(self):
        with self.assertRaises(ValueError):
            self.plan([(-1,0,0),(1,0,0)],[0],[0,0,.1],max_affected=1)
        for options in ({'tolerance_m':0},{'tolerance_m':True},{'axis':'Q'},
                {'linear':((0,0,0),(0,0,0),(0,0,0))},{'unit_m':0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.plan([(-1,0,0),(1,0,0)],[0],[0,0,.1],**options)

    def test_center_only_normal_motion_rejects_and_other_axes_reflect(self):
        with self.assertRaises(ValueError):
            self.plan([(0,0,0)],[0],[.1,0,0])
        offsets,_,_=self.plan([(0,-1,0),(0,1,0)],[1],[0,.2,.3],axis='Y')
        self.assertEqual(offsets,{0:(0.,-.2,.3),1:(0.,.2,.3)})
