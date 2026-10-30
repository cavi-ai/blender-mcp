import struct
import tempfile
import unittest
from pathlib import Path

from cavi_blender_mcp import textures


class TextureInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def png(self, width=16, height=8):
        value = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sIIBBBBB", 13, b"IHDR", width, height, 8, 2, 0, 0, 0)
        (self.root / "color.png").write_bytes(value)

    def test_color_receipt_identifies_exact_input_bytes_and_dimensions(self):
        self.png()
        value = textures.png_input(self.root, "color.png")
        self.assertEqual((value["width"], value["height"]), (16, 8))
        self.assertEqual(value["sha256"], "3d7d1d57de7f679a4ee525f1c739b1ff4d1c16e34bc0fb7b9f8442f611a8a347")

    def test_refuses_external_and_symlink_escaped_inputs(self):
        self.png()
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.png"
            target.write_bytes((self.root / "color.png").read_bytes())
            (self.root / "escape.png").symlink_to(target)
            for path in (str(target), "escape.png"):
                with self.assertRaisesRegex(ValueError, "workspace"):
                    textures.png_input(self.root, path)

    def test_refuses_oversized_and_non_png_inputs_before_decoding(self):
        self.png(width=100000)
        with self.assertRaisesRegex(ValueError, "dimensions"):
            textures.png_input(self.root, "color.png")
        (self.root / "color.png").write_bytes(b"not an image")
        with self.assertRaisesRegex(ValueError, "PNG"):
            textures.png_input(self.root, "color.png")
