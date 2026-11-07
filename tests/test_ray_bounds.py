import unittest

from cavi_blender_mcp import surface_ray


class RayBoundsTests(unittest.TestCase):
    def test_ray_bounds_keep_near_far_parallel_and_inside_cases(self):
        function=getattr(surface_ray,'bounds_intersect',None)
        self.assertIsNotNone(function,'Scene picking does not cull off-ray bounds')
        for origin,direction,distance,want in [([0,0,3],[0,0,-1],2,True),
                ([0,0,3],[0,0,-1],1.99,False),([3,0,3],[0,0,-1],10,False),
                ([0,0,3],[0,0,1],10,False),([0,0,0],[1,0,0],.01,True),
                ([1,0,3],[0,0,-1],4,True)]:
            with self.subTest(origin=origin,direction=direction,distance=distance):
                self.assertEqual(function(origin,direction,distance,[[-1,-1,-1],[1,1,1]]),want)
