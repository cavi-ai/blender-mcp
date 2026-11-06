import asyncio
import math
import unittest
from typing import ClassVar
from unittest.mock import patch

from cavi_blender_mcp import server


class FaceDensityTests(unittest.TestCase):
    geometry: ClassVar[dict] = {'vertices': [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)],
        'triangles': [[0, 1, 2], [0, 2, 3]], 'triangle_vertices': [[0, 1, 2], [0, 2, 3]]}
    uv: ClassVar[list] = [(0, 0), (1, 0), (1, 1), (0, 1)]
    region: ClassVar[dict] = {'bounds': [0, 0, 1, 1], 'texture_resolution': [2048, 1024], 'margin_px': 8}

    def test_physical_measurement_uses_world_area_and_rectangular_pixels(self):
        from cavi_blender_mcp.uv_density import measure

        result = measure(self.geometry, self.uv, [2048, 1024])
        self.assertEqual(result['world_area_m2'], 4)
        self.assertAlmostEqual(result['density_area_weighted'], math.sqrt(2048*1024/4))
        self.assertAlmostEqual(result['anisotropy_max'], 2)
        high = measure(self.geometry, self.uv, [16384, 8192])
        self.assertAlmostEqual(high['density_area_weighted'], math.sqrt(16384*8192/4))

    def test_degenerate_surfaces_and_uvs_cannot_claim_a_density(self):
        from cavi_blender_mcp.uv_density import measure

        for geometry, uv in ((self.geometry, [(0, 0)]*4),
                             ({**self.geometry, 'vertices': [(0, 0, 0)]*4}, self.uv)):
            with self.subTest(geometry=geometry, uv=uv), self.assertRaises(ValueError):
                measure(geometry, uv, [2048, 1024])

    def test_target_requires_region_and_refuses_an_additional_scale(self):
        from cavi_blender_mcp.uv_density import options

        self.assertIsNone(options(None, None, [1, 1]))
        self.assertEqual(options(512, self.region, [1, 1])['texture_resolution'], [2048, 1024])
        for target, region, scale in ((None, self.region, [1, 1]), (512, None, [1, 1]),
                (0, self.region, [1, 1]), (True, self.region, [1, 1]),
                (float('nan'), self.region, [1, 1]), (512, self.region, [2, 1])):
            with self.subTest(target=target, scale=scale), self.assertRaises(ValueError):
                options(target, region, scale)

    def test_density_transform_routes_existing_region_and_target_fields(self):
        spec = server.UVRegion(**self.region)
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.mesh_edit('uv_transform', 'Sleeve', uv_transform=server.UVTransform(
                faces=[1, 2], pivot=(.5, .5)), target_px_per_m=512, uv_region=spec,
                expected_mesh_sha256='a'*64, lease_id='owner'))
        self.assertEqual(call.call_args.args, ('transform_uv',))
        self.assertEqual(call.call_args.kwargs['target_px_per_m'], 512)
        self.assertEqual(call.call_args.kwargs['uv_region']['texture_resolution'], [2048, 1024])
        for args in ({'target_px_per_m': 512}, {'uv_region': spec}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                asyncio.run(server.mesh_edit('uv_transform', 'Sleeve',
                    uv_transform=server.UVTransform(faces=[1]), **args))
