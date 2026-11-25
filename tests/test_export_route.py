"""Export routing keeps distinct bridge operations and one triangulate refusal."""

import unittest

from cavi_blender_mcp.export_route import TRIANGULATE_MESSAGE, route_asset
from cavi_blender_mcp.server import pick


def asset_values(**overrides):
    values = {
        'name': None, 'names': None, 'preserve_instances': None, 'include_empties': None,
        'image': None, 'prompt': None, 'resolution': None, 'quality': None, 'views': None,
        'guide': None, 'bbox': None, 'lods': None, 'collision': None, 'animations': None, 'textures': None,
        'bake_pair': None, 'axis': None, 'baked_animation': None, 'animation_sample_step': None,
        'assembly': None, 'uv_layer': None, 'expected_sha256': None, 'triangulate': None,
        'deform_only': None,
    }
    values.update(overrides)
    return values


class ExportRouteTests(unittest.TestCase):
    def route(self, path, **overrides):
        return route_asset('export', path, asset_values(**overrides), lease_id=None, pick=pick)

    def test_fbx_triangulate_true_selects_the_server_operation(self):
        for options in ({}, {'animations': True}):
            with self.subTest(options=options):
                routed = self.route('asset.fbx', names=['Skin'], triangulate=True, **options)
                self.assertEqual(routed.operation, 'export_asset')
                self.assertIs(routed.params['triangulate'], True)

    def test_generate_carries_a_bbox_that_export_refuses(self):
        values = asset_values(image='input.png', bbox=(0.6, 0.6, 1.2))
        routed = route_asset('generate', 'mesh.glb', values, lease_id=None, pick=pick)
        self.assertEqual(routed.args, ('input.png', 'mesh.glb', None, None, None, None, (0.6, 0.6, 1.2)))
        with self.assertRaisesRegex(ValueError, 'bbox'):
            self.route('asset.glb', names=['Skin'], bbox=(0.6, 0.6, 1.2))

    def test_glb_triangulate_true_raises_the_shared_message(self):
        with self.assertRaises(ValueError) as caught:
            self.route('asset.glb', names=['Skin'], triangulate=True)
        self.assertEqual(str(caught.exception), TRIANGULATE_MESSAGE)

    def test_default_static_fbx_selects_export_mesh(self):
        routed = self.route('asset.fbx', names=['Skin'])
        self.assertEqual(routed.operation, 'export_mesh')
        self.assertNotIn('triangulate', routed.params)

    def test_assembly_and_uv_selections_stay_distinct(self):
        cases = [
            ({'assembly': True}, 'export_assembly'),
            ({'uv_layer': 'Atlas'}, 'export_uv_asset'),
            ({'assembly': True, 'uv_layer': 'Atlas'}, 'export_uv_assembly'),
            ({'assembly': True, 'triangulate': True}, 'export_assembly'),
            ({'uv_layer': 'Atlas', 'triangulate': True}, 'export_uv_asset'),
            ({'assembly': True, 'uv_layer': 'Atlas', 'triangulate': True}, 'export_uv_assembly'),
        ]
        for options, operation in cases:
            with self.subTest(options=options):
                self.assertEqual(self.route('asset.fbx', names=['Skin'], **options).operation,
                                 operation)
