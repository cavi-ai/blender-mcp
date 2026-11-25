"""Native PNG checks for perspective preview and review-sheet framing."""

import sys
import unittest
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge


class PreviewFramingTests(unittest.TestCase):
    def setUp(self):
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.scene = bpy.context.scene
        bpy.ops.mesh.primitive_cube_add(size=0.08)
        self.mesh = bpy.context.object
        self.scene.render.film_transparent = True
        self.scene.render.image_settings.color_mode = "RGBA"

    def preview_columns(self, name):
        result = bridge.dispatch("render_preview", {
            "path": name, "resolution": 256, "direction": [0, -1, 0],
        })
        image = bpy.data.images.load(result["path"], check_existing=False)
        try:
            pixels = np.empty(256 * 256 * 4, dtype=np.float32)
            image.pixels.foreach_get(pixels)
        finally:
            bpy.data.images.remove(image)
        return np.flatnonzero((pixels.reshape(256, 256, 4)[..., 3] > 0.5).any(axis=0))

    def test_preview_respects_non_square_pixel_aspect(self):
        self.scene.render.pixel_aspect_y = 2
        columns = self.preview_columns("non-square.png")
        self.assertGreater(columns[0], 0)
        self.assertLess(columns[-1], 255)
        self.assertGreater(len(columns), 128)
        self.assertEqual(self.scene.render.pixel_aspect_y, 2)

    def test_preview_keeps_render_only_array_copies(self):
        modifier = self.mesh.modifiers.new("Render array", "ARRAY")
        modifier.count = 2
        modifier.relative_offset_displace = (1.5, 0, 0)
        modifier.show_viewport = False
        columns = self.preview_columns("render-only-array.png")
        self.assertEqual(np.count_nonzero(np.diff(columns) > 1), 1)
        self.assertGreater(columns[0], 0)
        self.assertLess(columns[-1], 255)
        self.assertFalse(modifier.show_viewport)
        self.assertTrue(modifier.show_render)

    def test_perspective_review_tile_respects_pixel_aspect(self):
        self.scene.render.pixel_aspect_y = 2
        projected = []

        def record_camera(scene):
            for corner in self.mesh.bound_box:
                point = self.mesh.matrix_world @ Vector(corner)
                projected.append(world_to_camera_view(scene, scene.camera, point))

        bpy.app.handlers.render_pre.append(record_camera)
        try:
            result = bridge.dispatch("review_sheet", {
                "path": "perspective-sheet.png", "resolution": 256, "views": ["persp"],
            })
        finally:
            bpy.app.handlers.render_pre.remove(record_camera)
        self.assertTrue(Path(result["path"]).is_file())
        self.assertEqual(len(projected), 8)
        self.assertTrue(all(0 < point.x < 1 and 0 < point.y < 1 for point in projected),
                        projected)
        self.assertEqual(self.scene.render.pixel_aspect_y, 2)


if __name__ == "__main__":
    bridge._workspace = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
    unittest.main(argv=[sys.argv[0]], verbosity=2)
