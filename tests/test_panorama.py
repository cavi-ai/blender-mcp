import asyncio
import hashlib
import json
import os
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
