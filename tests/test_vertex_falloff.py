"""Physical edge distance yields smooth weights without reaching disconnected surfaces."""
import unittest

from cavi_blender_mcp import vertex_edit


class VertexFalloffTests(unittest.TestCase):
    def weights(self, vertices, edges, seeds, radius, **metric):
        function = getattr(vertex_edit,'geodesic_weights',None)
        self.assertIsNotNone(function,'Connected proportional vertex editing is missing')
        return dict(function(vertices,edges,seeds,radius,**metric))

    def test_smooth_weights_use_metres_and_preserve_disconnected_coincident_points(self):
        points = [(0,0,0),(1,0,0),(2,0,0),(0,2,0),(0,0,0)]
        weights = self.weights(points,[(0,1),(1,2),(0,3)],[0],.05,
            linear=((2,0,0),(0,3,0),(0,0,1)),unit_m=.01)
        self.assertEqual(set(weights),{0,1,2})
        for index,wanted in ((0,1),(1,.648),(2,.104)):
            self.assertAlmostEqual(weights[index],wanted)

    def test_edge_paths_follow_the_surface_instead_of_crossing_a_fold(self):
        points = [(0,0,0),(0,.02,0),(.02,.02,0),(.02,0,0)]
        self.assertNotIn(3,self.weights(points,[(0,1),(1,2),(2,3)],[0],.05))
        direct = self.weights(points,[(0,1),(1,2),(2,3),(0,3)],[0],.05)
        self.assertAlmostEqual(direct[3],.648)
        self.assertEqual(self.weights(points,[(0,1),(1,2),(2,3)],[0,3],.01),{0:1,3:1})

    def test_weighted_points_keep_the_same_morph_displacement(self):
        basis = vertex_edit.translated([(0,0,0),(1,0,0)],[0,0,.5],weights=[1,.648])
        morph = vertex_edit.translated([(0,0,.2),(1,0,.2)],[0,0,.5],weights=[1,.648])
        self.assertAlmostEqual(basis[1][2],.324,delta=1e-7)
        self.assertAlmostEqual(morph[1][2]-basis[1][2],.2,delta=1e-7)

    def test_invalid_radius_metric_and_affected_vertex_overflow_fail_before_editing(self):
        for radius in (0,-1,True,float('nan')):
            with self.subTest(radius=radius), self.assertRaises(ValueError):
                self.weights([(0,0,0)],[],[0],radius)
        with self.assertRaises(ValueError):
            self.weights([(0,0,0),(1,0,0)],[(0,1)],[0],2,max_affected=1)
        for metric in ({'unit_m':0},{'unit_m':float('nan')},{'linear':((1,0,0),)}):
            with self.subTest(metric=metric), self.assertRaises(ValueError):
                self.weights([(0,0,0)],[],[0],1,**metric)
        for weights in ([],[-1],[True],[float('nan')]):
            with self.subTest(weights=weights), self.assertRaises(ValueError):
                vertex_edit.translated([(0,0,0)],[0,0,.5],weights=weights)
