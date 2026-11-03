import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from cavi_blender_mcp import neural_worker


class NeuralImageTests(unittest.TestCase):
    def prepare(self, image):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "character.png"
            image.save(path)
            return neural_worker.prepare_image(path)

    def test_transparent_reference_preserves_white_foreground(self):
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        image.paste((255, 255, 255, 255), (4, 4, 12, 12))
        prepared = self.prepare(image)
        self.assertEqual(prepared.size, (512, 512))
        self.assertEqual(prepared.getpixel((256, 256)), (255, 255, 255))
        self.assertEqual(prepared.getpixel((0, 0)), (128, 128, 128))

    def test_translucent_white_foreground_keeps_its_provided_alpha(self):
        image = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        image.paste((255, 255, 255, 254), (4, 4, 12, 12))
        prepared = self.prepare(image)
        self.assertGreater(prepared.getpixel((256, 256))[0], 250)

    def test_opaque_white_background_still_uses_background_removal(self):
        image = Image.new("RGB", (16, 16), (255, 255, 255))
        image.paste((150, 30, 20), (4, 4, 12, 12))
        prepared = self.prepare(image)
        self.assertEqual(prepared.getpixel((256, 256)), (150, 30, 20))
        self.assertEqual(prepared.getpixel((0, 0)), (128, 128, 128))

    def test_empty_transparent_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "visible foreground"):
            self.prepare(Image.new("RGBA", (16, 16), (0, 0, 0, 0)))

    def test_oversized_reference_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "4096"):
            self.prepare(Image.new("RGBA", (4097, 1), (10, 20, 30, 255)))


class NeuralColorTests(unittest.TestCase):
    def test_gltf_midtones_are_linear_instead_of_display_encoded(self):
        colors = np.array([[128, 64, 32, 255]], dtype=np.uint8)
        encoded = neural_worker.linearize_vertex_colors(colors)
        np.testing.assert_array_equal(encoded, [[55, 13, 4, 255]])

    def test_black_white_and_transparency_survive_export(self):
        colors = np.array([[0, 255, 0, 128], [255, 0, 255, 0]], dtype=np.uint8)
        np.testing.assert_array_equal(neural_worker.linearize_vertex_colors(colors), colors)

    def test_color_conversion_preserves_source_colors(self):
        colors = np.array([[128, 64, 32, 253]], dtype=np.uint8)
        original = colors.copy()
        encoded = neural_worker.linearize_vertex_colors(colors)
        np.testing.assert_array_equal(colors, original)
        self.assertEqual(encoded.dtype, np.uint8)


if __name__ == "__main__":
    unittest.main()
