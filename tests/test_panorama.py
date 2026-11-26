import asyncio
import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from cavi_blender_mcp import server
from cavi_blender_mcp.panorama import panorama
from cavi_blender_mcp.panorama_seam import wrap

FAKE_AGENT = Path(__file__).with_name("fake_image_agent.py")


def seam(image):
    """Mean step across the wrap seam and across the column next to it."""
    pixels = image.convert("L").load()
    width, height = image.size
    across = sum(abs(pixels[width - 1, y] - pixels[0, y]) for y in range(height)) / height
    inside = sum(abs(pixels[1, y] - pixels[0, y]) for y in range(height)) / height
    return across, inside


def read_exr(path):
    """Header attributes and an (R, G, B) reader for an uncompressed scanline EXR of half channels."""
    data = path.read_bytes()
    position, attributes = 8, {}
    while data[position]:
        name, kind = data[position:].split(b"\0", 2)[:2]
        position += len(name) + len(kind) + 2
        size = struct.unpack_from("<i", data, position)[0]
        attributes[name] = (kind, data[position + 4:position + 4 + size])
        position += 4 + size
    _, _, right, bottom = struct.unpack("<4i", attributes[b"dataWindow"][1])
    width = right + 1
    offsets = struct.unpack_from(f"<{bottom + 1}Q", data, position + 1)

    def pixel(x, y):
        block = offsets[y]
        assert struct.unpack_from("<2i", data, block) == (y, 6 * width)
        blue, green, red = (struct.unpack_from("<e", data, block + 8 + 2 * (plane * width + x))[0]
                            for plane in range(3))
        return red, green, blue

    return data[:8], attributes, pixel


def scene_linear(code):
    """The documented EXR value of an 8-bit sRGB code: sRGB decoding, then inverse Reinhard to white 16."""
    encoded = code / 255
    decoded = encoded / 12.92 if encoded <= 0.04045 else ((encoded + 0.055) / 1.055) ** 2.4
    return decoded / (1 - decoded * 15 / 16)


class PanoramaTests(unittest.TestCase):
    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.work, self.record, self.model = (Path(root.name) / name for name in ("workspace", "record", "model"))
        for folder in (self.work, self.record, self.model):
            folder.mkdir()
        self.settings = {"CAVI_IMAGE_MLX_PYTHON": sys.executable, "CAVI_IMAGE_MLX_AGENT": str(FAKE_AGENT),
                         "CAVI_IMAGE_MLX_MODEL": str(self.model), "FAKE_IMAGE_RECORD": str(self.record)}

    def generate(self, prompt="a sunny meadow", path="sky.png", **extra):
        with patch.dict(os.environ, {**self.settings, **extra}):
            return panorama(self.work, prompt, path)

    def assert_nothing_published(self):
        self.assertFalse((self.work / "sky.png").exists())
        self.assertFalse(list(self.work.glob(".cavi-panorama-*")))

    def test_the_published_panorama_wraps_where_the_raw_image_jumps(self):
        report = self.generate()
        request = json.loads((self.record / "request.json").read_text())
        self.assertEqual((request["width"], request["height"], request["steps"]), (2048, 1024, 30))
        self.assertTrue(request["prompt"].startswith("a sunny meadow, seamless 360 degree equirectangular"))
        with Image.open(self.work / "sky.png") as published:
            self.assertEqual(published.size, (2048, 1024))
            across, inside = seam(published)
        self.assertLess(across, 3)
        self.assertLess(inside, 3)
        self.assertEqual(report["prompt_sha256"], hashlib.sha256(b"a sunny meadow").hexdigest())
        self.assertEqual((report["seconds"], report["seam_band"]), (12.5, 128))
        self.assertFalse(list(self.work.glob(".cavi-panorama-*")))

    def test_an_exr_path_publishes_scene_linear_half_floats_above_display_white(self):
        self.assertNotIn("white", self.generate(path="sky.png"))
        report = self.generate(path="sky.exr")
        self.assertEqual((report["white"], report["width"], report["height"]), (16, 2048, 1024))
        magic, attributes, pixel = read_exr(self.work / "sky.exr")
        self.assertEqual(magic, b"\x76\x2f\x31\x01\x02\0\0\0")
        self.assertEqual(attributes[b"compression"], (b"compression", b"\0"))
        channels = attributes[b"channels"][1]
        for index, name in enumerate(b"BGR"):
            self.assertEqual(channels[18 * index], name)
            self.assertEqual(struct.unpack_from("<i", channels, 18 * index + 2)[0], 1)
        with Image.open(self.work / "sky.png") as published:
            codes = published.convert("RGB")
        brightest = (0, 0)
        seam_start = report["width"] - report["seam_band"]
        for x in range(0, seam_start, 89):
            for y in (0, 511, 1023):
                for value, code in zip(pixel(x, y), codes.getpixel((x, y)), strict=True):
                    self.assertAlmostEqual(value, scene_linear(code), delta=scene_linear(code) / 500)
                brightest = max(brightest, (pixel(x, y)[0], codes.getpixel((x, y))[0]))
        self.assertGreater(brightest[0], 4)
        self.assertGreater(brightest[1], 230)
        # The fixture fades from nearly black on the right to white on the left.
        midpoint = seam_start + report["seam_band"] // 2 - 1
        self.assertEqual(pixel(midpoint, 300), (8.0, 8.0, 8.0))
        self.assertEqual(pixel(2047, 300), pixel(0, 300))
        self.assertFalse(list(self.work.glob(".cavi-panorama-*")))

    def test_configured_values_reach_the_image_agent_and_the_seam(self):
        configured = {"CAVI_IMAGE_MLX_WIDTH": "1024", "CAVI_IMAGE_MLX_DEFAULT_STEPS": "4", "CAVI_IMAGE_MLX_STEPS": "99",
                      "CAVI_IMAGE_MLX_SEED": "3", "CAVI_IMAGE_MLX_SEAM_BAND": "64", "CAVI_IMAGE_MLX_WHITE": "8",
                      "CAVI_IMAGE_MLX_TIMEOUT": "600",
                      "FAKE_IMAGE_EXPECT": json.dumps({"width": 1024, "height": 512, "seed": 3, "timeout": 600})}
        self.generate(path="sky.png", **configured)
        report = self.generate(path="sky.exr", **configured)
        request = json.loads((self.record / "request.json").read_text())
        self.assertEqual([request[name] for name in ("width", "height", "steps", "seed")], [1024, 512, 4, 3])
        self.assertEqual([report[name] for name in ("width", "height", "steps", "seam_band", "white")],
                         [1024, 512, 4, 64, 8.0])
        _, _, pixel = read_exr(self.work / "sky.exr")
        with Image.open(self.work / "sky.png") as published:
            self.assertEqual(published.size, (1024, 512))
            codes = published.convert("RGB")
        for x in (0, 300, 900):
            encoded = codes.getpixel((x, 100))[0] / 255
            decoded = encoded / 12.92 if encoded <= 0.04045 else ((encoded + 0.055) / 1.055) ** 2.4
            self.assertAlmostEqual(pixel(x, 100)[0], decoded / (1 - decoded * 7 / 8), delta=decoded / 100)
        self.assertEqual(pixel(1023, 100), pixel(0, 100))
        for key, value in (("CAVI_IMAGE_MLX_WIDTH", "1025"), ("CAVI_IMAGE_MLX_SEAM_BAND", "512"),
                           ("CAVI_IMAGE_MLX_FAST_TIMEOUT", "0")):
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(RuntimeError, key),
                patch.dict(os.environ, {**self.settings, **configured, key: value}),
            ):
                panorama(self.work, "a sunny meadow", "other.png", "fast" if "FAST" in key else None)
            self.assertFalse((self.work / "other.png").exists())

    def test_exr_refuses_invalid_white_before_running_the_agent(self):
        for value in ("0.5", "70000"):
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "CAVI_IMAGE_MLX_WHITE"):
                self.generate(path="sky.exr", CAVI_IMAGE_MLX_WHITE=value)
            self.assertFalse((self.work / "sky.exr").exists())
            self.assertFalse((self.record / "request.json").exists())

    def test_png_ignores_the_exr_white_setting(self):
        report = self.generate(CAVI_IMAGE_MLX_WHITE="bad")
        self.assertNotIn("white", report)
        with Image.open(self.work / "sky.png") as published:
            self.assertEqual(published.format, "PNG")

    def test_a_ramp_jumps_at_its_seam_until_it_is_wrapped(self):
        ramp = Image.linear_gradient("L").rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT)
        ramp = ramp.resize((512, 256)).convert("RGB")
        self.assertGreater(seam(ramp)[0], 200)
        wrapped = wrap(ramp, 32)
        self.assertEqual(wrapped.size, (512, 256))
        self.assertLess(seam(wrapped)[0], 4)
        self.assertEqual(wrapped.getpixel((200, 20)), ramp.getpixel((200, 20)))

    def test_requests_outside_the_contract_publish_nothing(self):
        for prompt, path, message in (("", "sky.png", "1..1000"), ("x" * 1001, "sky.png", "1..1000"),
                                      ("meadow", "sky.jpg", ".png")):
            with self.subTest(prompt=prompt[:8], path=path), self.assertRaisesRegex(ValueError, message):
                self.generate(prompt, path)
            self.assert_nothing_published()
        with self.assertRaisesRegex(RuntimeError, "invalid_arguments"):
            self.generate(FAKE_IMAGE_MODE="error")
        self.assert_nothing_published()
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(RuntimeError, "CAVI_IMAGE_MLX_PYTHON"):
            panorama(self.work, "meadow", "sky.png")
        self.assert_nothing_published()

    def test_the_server_routes_a_prompt_to_the_panorama(self):
        settings = {**self.settings, "CAVI_BLENDER_WORKSPACE": str(self.work)}
        with (
            patch.dict(os.environ, settings),
            patch.object(server, "call", side_effect=AssertionError("Unrelated scene accessed")),
        ):
            report = asyncio.run(server.asset_io("generate", "sky.png", prompt="a sunny meadow", quality="fast"))
            with self.assertRaisesRegex(ValueError, "Not valid for action=.*: image"):
                asyncio.run(server.asset_io("generate", "other.png", prompt="meadow", image="input.png"))
        self.assertEqual((report["steps"], report["quality"]), (12, "fast"))
        self.assertTrue((self.work / "sky.png").is_file())


if __name__ == "__main__":
    unittest.main()
