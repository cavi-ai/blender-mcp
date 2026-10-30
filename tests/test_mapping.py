import math
import unittest

from cavi_blender_mcp.mapping import measure_triangle, summarize


class MappingTests(unittest.TestCase):
    points = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
    uv = ((0, 0), (1, 0), (0, 1))

    def test_unit_surface_has_1024_pixels_per_meter(self):
        result = measure_triangle(self.points, self.uv, (1024, 1024))
        self.assertEqual(result["world_area_m2"], 0.5)
        self.assertEqual(result["uv_area"], 0.5)
        self.assertEqual(result["density"], 1024)
        self.assertEqual(result["anisotropy"], 1)

    def test_physical_scale_and_texture_dimensions_affect_density(self):
        scaled = [(x * 2, y * 2, z) for x, y, z in self.points]
        self.assertEqual(measure_triangle(scaled, self.uv, (1024, 1024))["density"], 512)
        result = measure_triangle(self.points, self.uv, (2048, 1024))
        self.assertAlmostEqual(result["density"], math.sqrt(2048 * 1024))
        self.assertEqual(result["anisotropy"], 2)

    def test_equal_uv_area_does_not_hide_directional_stretch(self):
        stretched = [(0, 0), (2, 0), (0, 0.5)]
        result = measure_triangle(self.points, stretched, (1024, 1024))
        self.assertEqual(result["density"], 1024)
        self.assertEqual(result["anisotropy"], 4)

    def test_degenerate_uv_and_world_triangles_have_no_density(self):
        for points, uv in [
            (self.points, [(0, 0)] * 3),
            ([(0, 0, 0)] * 3, self.uv),
            (self.points, None),
        ]:
            self.assertIsNone(measure_triangle(points, uv, (1024, 1024))["density"])

    def test_invalid_numbers_are_refused(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            measure_triangle([(float("nan"), 0, 0)] * 3, self.uv, (1024, 1024))

    def test_area_weighted_quantiles_ignore_a_tiny_triangle_outlier(self):
        regular = measure_triangle(self.points, self.uv, (1024, 1024))
        tiny = dict(regular, world_area_m2=0.00001, density=100000)
        result = summarize([regular, tiny])
        self.assertEqual(result["density_p90"], 1024)
        self.assertEqual(result["density_max"], 100000)
