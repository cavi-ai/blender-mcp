import math
import unittest

from cavi_blender_mcp.framing import effective_fov, fit_sphere

SENSOR = 36.0
FOCAL = 50.0
FOV_X = 2 * math.atan(SENSOR / 2 / FOCAL)
SQUARE = (FOV_X, FOV_X)
WIDE = (FOV_X, 2 * math.atan(SENSOR * 9 / 16 / 2 / FOCAL))


def coverage(radius, distance, fovs):
    """Fraction of the narrower half-frame covered by the sphere silhouette."""
    half = min(fovs) / 2
    return math.tan(math.asin(radius / distance)) / math.tan(half)


class FramingTests(unittest.TestCase):
    def test_old_formula_leaves_small_assets_tiny(self):
        self.assertLess(coverage(0.05, max(0.05 * 3.5, 2), SQUARE), 0.10)

    def test_sphere_fills_frame_and_lies_inside_clip_range(self):
        for radius in (1e-4, 0.05, 1, 10, 1000):
            for fovs in (SQUARE, WIDE):
                with self.subTest(radius=radius, fovs=fovs):
                    distance, near, far = fit_sphere(radius, *fovs)
                    self.assertTrue(0.8 <= coverage(radius, distance, fovs) <= 1.0)
                    self.assertTrue(0 < near <= distance - radius)
                    self.assertGreaterEqual(far, distance + radius)

    def test_radius_below_minimum_is_guarded(self):
        distance, near, far = fit_sphere(0, *SQUARE)
        self.assertGreater(distance, 0)
        self.assertTrue(0 < near < distance < far)


class EffectiveFovTests(unittest.TestCase):
    def test_auto_square_uses_sensor_width_on_both_axes(self):
        x, y = effective_fov(50, 36, 24, "AUTO", 512, 512)
        self.assertAlmostEqual(x, FOV_X)
        self.assertAlmostEqual(y, FOV_X)

    def test_auto_follows_larger_dimension(self):
        x, y = effective_fov(50, 36, 24, "AUTO", 1600, 900)
        self.assertAlmostEqual(x, FOV_X)
        self.assertAlmostEqual(math.tan(y / 2), math.tan(FOV_X / 2) * 9 / 16)
        x, y = effective_fov(50, 36, 24, "AUTO", 900, 1600)
        self.assertAlmostEqual(y, FOV_X)
        self.assertAlmostEqual(math.tan(x / 2), math.tan(FOV_X / 2) * 9 / 16)

    def test_horizontal_and_vertical_fit(self):
        x, y = effective_fov(50, 36, 24, "HORIZONTAL", 900, 1600)
        self.assertAlmostEqual(x, FOV_X)
        self.assertAlmostEqual(math.tan(y / 2), math.tan(FOV_X / 2) * 16 / 9)
        x, y = effective_fov(50, 36, 24, "VERTICAL", 1600, 900)
        self.assertAlmostEqual(y, 2 * math.atan(24 / 2 / 50))
        self.assertAlmostEqual(math.tan(x / 2), math.tan(y / 2) * 16 / 9)

    def test_square_preview_sphere_coverage(self):
        fovs = effective_fov(50, 36, 24, "AUTO", 512, 512)
        distance, _, _ = fit_sphere(0.05, *fovs)
        self.assertGreaterEqual(coverage(0.05, distance, fovs), 0.85)
