"""Terrain noise keeps a stable amplitude and a full border window."""
import unittest

import numpy as np

from cavi_blender_mcp.terrain_field import noise, prefilter


class TerrainFieldTests(unittest.TestCase):
    def test_seeds_keep_their_own_amplitude_instead_of_filling_the_range(self):
        first, second = noise(9, 3, 3, 3), noise(9, 4, 3, 3)
        self.assertGreaterEqual(float(first.min()), 0)
        self.assertLessEqual(float(first.max()), 1)
        self.assertTrue(float(first.min()) > 0 or float(first.max()) < 1)
        self.assertNotAlmostEqual(float(first.max() - first.min()),
                                   float(second.max() - second.min()), places=3)

    def test_reflected_border_uses_a_full_window(self):
        grid = np.array([[index % 2 for index in range(33)] for _ in range(33)], np.float64)
        filtered = prefilter(grid, 3)
        self.assertTrue(np.all((filtered > 0.4) & (filtered < 0.6)), filtered)
        self.assertTrue(np.allclose(prefilter(np.ones((8, 8)), 3), 1))
