"""World rays retain physical distances through mirrored, scaled object transforms."""
import importlib.util
import unittest

from cavi_blender_mcp import scene_models


class SurfaceRayTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('cavi_blender_mcp.surface_ray'),
                             'World-space surface rays are missing')
        from cavi_blender_mcp import surface_ray
        return surface_ray

    def test_mirrored_nonuniform_transform_keeps_the_metres_distance_cap(self):
        ray=self.module().local_ray([5,5,11],[0,0,-2],.08,
            [[-2,0,0,7],[0,3,0,2],[0,0,4,3],[0,0,0,1]],.01)
        self.assertEqual(ray[0],[1.,1.,2.])
        self.assertEqual(ray[1],[0.,0.,-1.])
        self.assertAlmostEqual(ray[2],2.)

    def test_shear_changes_local_direction_without_changing_the_world_ray(self):
        origin,direction,distance=self.module().local_ray([4,3,0],[0,2,0],2.,
            [[1,1,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],1.)
        self.assertEqual(origin,[1.,3.,0.])
        self.assertAlmostEqual(direction[0],-2**-.5)
        self.assertAlmostEqual(direction[1],2**-.5)
        self.assertAlmostEqual(distance,2*2**.5)

    def test_zero_nonfinite_singular_and_native_overflow_rays_reject(self):
        identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]]
        for origin,direction,cap,matrix,unit in [([0,0,0],[0,0,0],1,identity,1),
                ([float('nan'),0,0],[0,0,1],1,identity,1),
                ([0,0,0],[0,0,1],0,identity,1),
                ([0,0,0],[0,0,1],1,[[0]*4]*4,1),
                ([0,0,0],[0,0,1],1,identity,0),
                ([4e38,0,0],[0,0,1],1,identity,1)]:
            with self.subTest(origin=origin,cap=cap,unit=unit),self.assertRaises(ValueError):
                self.module().local_ray(origin,direction,cap,matrix,unit)

    def test_typed_ray_requires_explicit_distance_and_rejects_unknown_options(self):
        model=getattr(scene_models,'SurfaceRay',None)
        self.assertIsNotNone(model,'Typed surface ray schema is missing')
        value={'origin_world':[0,0,1],'direction_world':[0,0,-1],'max_distance_m':2}
        self.assertFalse(model.model_validate(value).evaluated)
        for extra in ({'direction_world':[0,0,0]},{'max_distance_m':None},
                      {'direction_world':[True,0,1]},{'select':True}):
            with self.subTest(extra=extra),self.assertRaises(ValueError):
                model.model_validate({**value,**extra})
