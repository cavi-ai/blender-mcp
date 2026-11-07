"""Camera pixels unproject at pixel centers and retain the native clipping interval."""
import unittest

from cavi_blender_mcp import scene_models, surface_ray


class CameraRayTests(unittest.TestCase):
    def ray(self,pixel,size,projection,kind='PERSP',near=1.,far=10.):
        function=getattr(surface_ray,'pixel_ray',None)
        self.assertIsNotNone(function,'Camera pixel unprojection is missing')
        return function(pixel,size,projection,[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],kind,near,far)

    def test_perspective_center_starts_at_near_plane_and_stops_at_far_plane(self):
        origin,direction,span=self.ray([1,1],[3,3],
            [[1,0,0,0],[0,1,0,0],[0,0,-11/9,-20/9],[0,0,-1,0]])
        self.assertEqual(origin,[0.,0.,-1.])
        self.assertEqual(direction,[0.,0.,-1.])
        self.assertAlmostEqual(span,9.)

    def test_orthographic_top_left_uses_pixel_center_and_parallel_direction(self):
        origin,direction,span=self.ray([0,0],[2,2],
            [[.5,0,0,0],[0,.5,0,0],[0,0,-.5,-1.5],[0,0,0,1]],kind='ORTHO',far=5.)
        self.assertEqual(origin,[-1.,1.,-1.])
        self.assertEqual(direction,[0.,0.,-1.])
        self.assertAlmostEqual(span,4.)

    def test_projection_shift_changes_the_ray_and_off_axis_clip_distance(self):
        origin,direction,span=self.ray([1,1],[3,3],
            [[1,0,.2,0],[0,1,0,0],[0,0,-11/9,-20/9],[0,0,-1,0]])
        self.assertAlmostEqual(origin[0],.2)
        self.assertAlmostEqual(direction[0],.2/(1.04**.5))
        self.assertAlmostEqual(span,9*1.04**.5)

    def test_bad_pixel_size_projection_and_clips_reject(self):
        matrix=[[1,0,0,0],[0,1,0,0],[0,0,-11/9,-20/9],[0,0,-1,0]]
        for pixel,size,projection,kind,near,far in [([-1,0],[3,3],matrix,'PERSP',1,10),
                ([3,0],[3,3],matrix,'PERSP',1,10),([0,0],[0,3],matrix,'PERSP',1,10),
                ([0,0],[3,3],[[0]*4]*4,'PERSP',1,10),
                ([0,0],[3,3],matrix,'PANO',1,10),([0,0],[3,3],matrix,'PERSP',10,1)]:
            with self.subTest(pixel=pixel,kind=kind),self.assertRaises(ValueError):
                self.ray(pixel,size,projection,kind,near,far)

    def test_typed_camera_query_requires_a_matching_pixel_domain(self):
        model=getattr(scene_models,'CameraRay',None)
        self.assertIsNotNone(model,'Typed camera query is missing')
        value={'camera':'Hero','pixel':[12,15],'image_size':[64,48],'max_distance_m':10}
        self.assertFalse(model.model_validate(value).evaluated)
        for change in ({'pixel':[64,0]},{'image_size':[64,False]},
                       {'direction_world':[0,0,-1]},{'pixel':[float('nan'),0]}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                model.model_validate({**value,**change})
