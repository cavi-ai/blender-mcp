import asyncio
import unittest
from unittest.mock import patch

from cavi_blender_mcp import server


class UVRegionTests(unittest.TestCase):
    def test_region_requires_explicit_bounds_resolution_and_padding(self):
        from cavi_blender_mcp.uv_regions import region

        valid = {'bounds': [0, 0, 1, 1], 'texture_resolution': [2048, 1024], 'margin_px': 8}
        self.assertFalse(region(valid)['allow_overlap'])
        for changed in ({'bounds': [1, 0, 0, 1]}, {'texture_resolution': [True, 1024]},
                        {'bounds': [0, 0, float('nan'), 1]}, {'margin_px': -1},
                        {'bounds': [0, 0, .001, .001]}, {'allow_overlap': 'yes'}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                region({**valid, **changed})
        with self.assertRaises(ValueError):
            region({'bounds': [0, 0, 1, 1]})

    def test_pixel_mapping_preserves_aspect_for_rectangular_textures_and_udims(self):
        from cavi_blender_mcp.uv_regions import map_uv, region

        spec = region({'bounds': [1, 0, 2, 1], 'texture_resolution': [2048, 1024], 'margin_px': 8})
        origin, u, v = map_uv([(0, 0), (1, 0), (0, 1)], spec)
        self.assertAlmostEqual((u[0]-origin[0])*2048, (v[1]-origin[1])*1024)
        self.assertGreaterEqual((origin[0]-1)*2048, 8)
        self.assertGreaterEqual(origin[1]*1024, 8)
        self.assertLessEqual(v[1], 1-8/1024)

    def test_reservation_detects_crossing_triangles_and_allows_deliberate_reuse(self):
        from cavi_blender_mcp.uv_regions import region, reservation

        spec = region({'bounds': [0, 0, 1, 1], 'texture_resolution': [2048, 1024], 'margin_px': 8})
        crossing = [[(-2, .5), (2, .5), (0, 2)]]
        with self.assertRaisesRegex(ValueError, 'occupied'):
            reservation(crossing, spec)
        self.assertTrue(reservation([[(2, 0), (3, 0), (2, 1)]], spec)['checked'])
        self.assertFalse(reservation(crossing, {**spec, 'allow_overlap': True})['checked'])

    def test_face_unwrap_routes_only_its_own_parameters(self):
        spec = server.UVRegion(bounds=(.5, .5, 1, 1), texture_resolution=(2048, 1024), margin_px=8)
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.mesh_edit('unwrap_faces', 'Panel', face_indices=[7, 8], uv_layer='BakeAtlas',
                uv_region=spec, expected_mesh_sha256='a' * 64, lease_id='owner'))
        self.assertEqual(call.call_args.args, ('unwrap_faces',))
        args = call.call_args.kwargs
        self.assertEqual(args['face_indices'], [7, 8])
        self.assertEqual(args['uv_region']['texture_resolution'], [2048, 1024])
        self.assertEqual(args['expected_mesh_sha256'], 'a' * 64)
        with patch.object(server, 'call') as call:
            for action in ('unwrap', 'extrude_faces'):
                with self.assertRaisesRegex(ValueError, 'does not accept: uv_region'):
                    asyncio.run(server.mesh_edit(action, 'Panel', uv_region=spec))
            call.assert_not_called()

    def test_quality_refuses_overlaps_collapsed_faces_and_insufficient_gutters(self):
        from cavi_blender_mcp.uv_regions import quality, region

        spec = region({'bounds': [0, 0, 1, 1], 'texture_resolution': [1024, 512], 'margin_px': 8})
        first = [(.1, .1), (.3, .1), (.1, .3)]
        triangles = [[0, 1, 2], [3, 4, 5]]
        vertices = [[0, 1, 2], [3, 4, 5]]
        for second in (first, [(.5, .5)]*3,
                       [(.301, .1), (.5, .1), (.301, .3)],
                       [(.7, .7), (.99, .7), (.7, .999)]):
            with self.subTest(second=second):
                _, report = quality(first+second, triangles, vertices, spec)
                self.assertFalse(report['passed'], report)
        _, report = quality(first+[(.6, .6), (.8, .6), (.6, .8)], triangles, vertices, spec)
        self.assertTrue(report['passed'], report)
