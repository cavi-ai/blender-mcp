import asyncio
import contextlib
import hashlib
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import ClassVar
from unittest.mock import patch

from cavi_mcp_core import proc
from PIL import Image

from cavi_blender_mcp import generation, neural_worker, server
from cavi_blender_mcp.generation import generate
from cavi_blender_mcp.importing import inspect_glb

FAKE_AGENT = Path(__file__).with_name("fake_mlx_agent.py")


class GenerationTests(unittest.TestCase):
    def test_server_generation_uses_configured_workspace_without_reading_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            report = {"path": str(workspace / "mesh.glb")}
            with (
                patch.dict(os.environ, {"CAVI_BLENDER_WORKSPACE": str(workspace)}),
                patch.object(server, "call", side_effect=AssertionError("Unrelated scene accessed")),
                patch.object(server, "generate", return_value=report) as native,
            ):
                result = asyncio.run(server.asset_io("generate", "mesh.glb", image="input.png"))
            self.assertEqual(result, report)
            native.assert_called_once_with(workspace.resolve(), "input.png", "mesh.glb", None, None, None, None,
                                           None)

    def test_server_generation_defaults_to_runtime_workspace_without_a_bridge(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(server, "call", side_effect=ConnectionError("Bridge offline")),
            patch.object(server, "generate", return_value={}) as native,
        ):
            asyncio.run(server.asset_io("generate", "mesh.glb", image="input.png", resolution=96))
        native.assert_called_once_with((Path.home() / "Documents/CaviBlender").resolve(),
                                       "input.png", "mesh.glb", 96, None, None, None, None)

    def configured(self, work):
        return patch.dict(
            os.environ,
            {
                key: str(work)
                for key in ("CAVI_TRIPOSR_PYTHON", "CAVI_TRIPOSR_SOURCE", "CAVI_TRIPOSR_WEIGHTS")
            },
        )

    def test_generation_cannot_read_outside_workspace(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root) / "workspace"
            work.mkdir()
            outside = Path(root) / "private.png"
            outside.write_bytes(b"private")
            (work / "linked.png").symlink_to(outside)
            for image in ("../private.png", "linked.png"):
                with self.subTest(image=image), self.assertRaisesRegex(ValueError, "workspace"):
                    generate(work, image, "mesh.glb", 128)
            self.assertEqual(outside.read_bytes(), b"private")

    def test_existing_output_is_preserved_before_model_loading(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            (work / "mesh.glb").write_bytes(b"original")
            with self.assertRaises(FileExistsError):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertEqual((work / "mesh.glb").read_bytes(), b"original")

    def test_missing_runtime_does_not_download_or_create_an_asset(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {}, clear=True):
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            with self.assertRaisesRegex(RuntimeError, "CAVI_TRIPOSR"):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertFalse((work / "mesh.glb").exists())

    def test_success_publishes_only_the_worker_output(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")

            def complete(command, timeout, **kwargs):
                Path(command[3]).write_bytes(b"generated-glb")
                return proc.Result(0, '{"triangles": 12}', "")

            with self.configured(work), patch.object(proc, "run_sync", side_effect=complete):
                report = generate(work, "input.png", "mesh.glb", 128)
            self.assertEqual(report["triangles"], 12)
            self.assertEqual((work / "mesh.glb").read_bytes(), b"generated-glb")
            self.assertFalse(list(work.glob(".cavi-generation-*")))

    def test_timeout_leaves_no_published_or_temporary_asset(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            with (
                self.configured(work),
                patch.object(proc, "run_sync", side_effect=TimeoutError("worker")),
                self.assertRaisesRegex(RuntimeError, "180 seconds"),
            ):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertFalse((work / "mesh.glb").exists())
            self.assertFalse(list(work.glob(".cavi-generation-*")))

    def test_worker_failure_reports_exit_and_preserves_diagnostics(self):
        for code, stderr, stdout, detail in (
            (-9, "", "", "no diagnostics"),
            (2, " import failed ", "", "import failed"),
            (3, " ", "encoder stopped", "encoder stopped"),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                work = Path(root)
                (work / "input.png").write_bytes(b"input")

                def fail(command, timeout, *, exit_code=code, worker_stdout=stdout,
                         worker_stderr=stderr, **kwargs):
                    Path(command[3]).write_bytes(b"partial-glb")
                    return proc.Result(exit_code, worker_stdout, worker_stderr)

                with (
                    self.configured(work),
                    patch.object(proc, "run_sync", side_effect=fail),
                    self.assertRaisesRegex(RuntimeError, f"exit {code}.*{detail}"),
                ):
                    generate(work, "input.png", "mesh.glb", 128)
                self.assertFalse((work / "mesh.glb").exists())
                self.assertFalse(list(work.glob(".cavi-generation-*")))

    def test_unknown_provider_is_rejected_before_any_asset(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            with (
                self.configured(work),
                patch.dict(os.environ, {"CAVI_GENERATION_PROVIDER": "remote"}),
                self.assertRaisesRegex(ValueError, "triposg-mlx"),
            ):
                generate(work, "input.png", "mesh.glb")
            self.assertFalse((work / "mesh.glb").exists())

    def test_quality_tiers_apply_only_to_mlx_providers(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            for provider in ("triposr", "triposg"):
                with (
                    self.subTest(provider=provider),
                    self.configured(work),
                    patch.dict(os.environ, {"CAVI_GENERATION_PROVIDER": provider}),
                    self.assertRaisesRegex(ValueError, "triposg-mlx and trellis2-mlx"),
                ):
                    generate(work, "input.png", "mesh.glb", quality="fast")
            self.assertFalse((work / "mesh.glb").exists())

    def test_triposg_requires_its_own_runtime(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            with (
                self.configured(work),
                patch.dict(os.environ, {"CAVI_GENERATION_PROVIDER": "triposg"}),
                self.assertRaisesRegex(RuntimeError, "CAVI_TRIPOSG_PYTHON"),
            ):
                generate(work, "input.png", "mesh.glb")
            self.assertFalse((work / "mesh.glb").exists())

    def test_triposg_refuses_a_triposr_resolution(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            with (
                patch.dict(os.environ, {"CAVI_GENERATION_PROVIDER": "triposg"}),
                self.assertRaisesRegex(ValueError, "only to the TripoSR"),
            ):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertFalse((work / "mesh.glb").exists())

    def test_triposg_timeout_allows_ten_minutes_and_publishes_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")
            runtime = {f"CAVI_TRIPOSG_{key}": str(work) for key in ("PYTHON", "SOURCE", "WEIGHTS")}
            with (
                patch.dict(os.environ, {"CAVI_GENERATION_PROVIDER": "triposg", **runtime}),
                patch.object(proc, "run_sync", side_effect=TimeoutError("worker")),
                self.assertRaisesRegex(RuntimeError, "600 seconds"),
            ):
                generate(work, "input.png", "mesh.glb")
            self.assertFalse((work / "mesh.glb").exists())
            self.assertFalse(list(work.glob(".cavi-generation-*")))

    def test_a_competing_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")

            def race(command, timeout, **kwargs):
                Path(command[3]).write_bytes(b"generated-glb")
                (work / "mesh.glb").write_bytes(b"other-writer")
                return proc.Result(0, "{}", "")

            with (
                self.configured(work),
                patch.object(proc, "run_sync", side_effect=race),
                self.assertRaises(FileExistsError),
            ):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertEqual((work / "mesh.glb").read_bytes(), b"other-writer")


class WorkerProcessTests(unittest.TestCase):
    def background(self, script, timeout):
        """Run a worker that leaves a sleeping child; return the run outcome and its pid."""
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        marker = Path(root.name) / "child.pid"
        command = ["/bin/sh", "-c", f'sleep 30 & echo $! > "{marker}"; {script}']
        try:
            outcome = generation.run(command, dict(os.environ), timeout, time.monotonic() + timeout)
        except RuntimeError as exc:
            outcome = exc
        child = int(marker.read_text())
        self.addCleanup(_kill, child)
        return outcome, child

    def test_timeout_stops_the_worker_and_its_children(self):
        outcome, child = self.background("wait", 1)
        self.assertRegex(str(outcome), "exceeded 1 seconds")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _alive(child):
            time.sleep(.05)
        self.assertFalse(_alive(child), "The worker's child outlived the timeout")

    def test_a_finished_worker_is_not_held_by_a_background_child(self):
        outcome, _child = self.background("echo done", 5)
        self.assertNotIsInstance(outcome, RuntimeError, outcome)
        self.assertEqual((outcome.returncode, outcome.stdout.strip()), (0, "done"))


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill(pid):
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


class TripoSGMlxTests(unittest.TestCase):
    provider, prefix, model, name = "triposg-mlx", "CAVI_TRIPOSG_MLX", "triposg", "TripoSG"
    extra: ClassVar[dict] = {}

    def expected_frame(self, image):
        return neural_worker.prepare_image(image, background=(255, 255, 255), extent=427)

    def setUp(self):
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.work = Path(root.name) / "workspace"
        self.work.mkdir()
        self.record = Path(root.name) / "record"
        self.record.mkdir()
        self.checkpoint = Path(root.name) / "model"
        self.checkpoint.mkdir()
        cutout = Image.new("RGBA", (400, 800), (0, 0, 0, 0))
        cutout.paste((150, 30, 20, 255), (100, 0, 300, 800))
        cutout.save(self.work / "input.png")

    def settings(self, mode, **extra):
        return {
            "CAVI_GENERATION_PROVIDER": self.provider,
            f"{self.prefix}_PYTHON": sys.executable,
            f"{self.prefix}_AGENT": str(FAKE_AGENT),
            f"{self.prefix}_MODEL": str(self.checkpoint),
            "FAKE_AGENT_MODEL": self.model,
            "FAKE_AGENT_MODE": mode,
            "FAKE_AGENT_RECORD": str(self.record),
            **extra,
        }

    def generate(self, mode="ok", image="input.png", quality=None, **extra):
        options = {} if quality is None else {"quality": quality}
        with patch.dict(os.environ, self.settings(mode, **extra)):
            return generate(self.work, image, "mesh.glb", **options)

    def assert_nothing_published(self):
        self.assertFalse((self.work / "mesh.glb").exists())
        self.assertFalse(list(self.work.glob(".cavi-generation-*")))

    def test_success_publishes_the_mesh_and_reports_the_run(self):
        report = self.generate()
        published = self.work / "mesh.glb"
        self.assertEqual(published.read_bytes(), (self.record / "mesh.glb").read_bytes())
        self.assertEqual(
            report,
            {
                "provider": self.name,
                "backend": "mlx-3d",
                "vertices": 249896,
                "faces": 499990,
                "seconds": 143.536,
                "stage_seconds": {"load": 0.864, "sampling": 61.804, "decode_refine": 33.015},
                "peak_memory_gb": 10.301,
                "input_sha256": hashlib.sha256((self.work / "input.png").read_bytes()).hexdigest(),
                "quality": "default",
                **self.extra,
                "path": str(published.resolve()),
                "bytes": 28,
            },
        )
        self.assertFalse(list(self.work.glob(".cavi-generation-*")))

    def test_fast_quality_reaches_the_agent_and_is_reported(self):
        report = self.generate(quality="fast", FAKE_AGENT_QUALITY="fast")
        self.assertEqual(report["quality"], "fast")
        self.assertTrue((self.work / "mesh.glb").is_file())

    def test_the_server_forwards_the_quality_tier(self):
        settings = {**self.settings("ok", FAKE_AGENT_QUALITY="fast"), "CAVI_BLENDER_WORKSPACE": str(self.work)}
        with (
            patch.dict(os.environ, settings),
            patch.object(server, "call", side_effect=AssertionError("Unrelated scene accessed")),
        ):
            report = asyncio.run(server.asset_io("generate", "mesh.glb", image="input.png", quality="fast"))
        self.assertEqual(report["quality"], "fast")
        self.assertTrue((self.work / "mesh.glb").is_file())

    def test_unknown_quality_is_refused_before_any_asset(self):
        with self.assertRaisesRegex(ValueError, "fast, default or high"):
            self.generate(quality="ultra")
        self.assert_nothing_published()
        self.assertFalse((self.record / "image.png").exists())

    def test_high_quality(self):
        with self.assertRaisesRegex(ValueError, "high applies only to the trellis2-mlx"):
            self.generate(quality="high")
        self.assert_nothing_published()
        self.assertFalse((self.record / "image.png").exists())

    def test_the_tool_schema_offers_the_high_tier(self):
        settings = {**self.settings("ok"), "CAVI_BLENDER_WORKSPACE": str(self.work)}
        with (
            patch.dict(os.environ, settings),
            patch.object(server, "call", side_effect=AssertionError("Unrelated scene accessed")),
            self.assertRaisesRegex(Exception, "high applies only to the trellis2-mlx"),
        ):
            asyncio.run(server.mcp.call_tool("asset_io", {
                "action": "generate", "path": "mesh.glb", "image": "input.png", "quality": "high"}))
        self.assert_nothing_published()

    def test_the_agent_receives_the_framed_image(self):
        self.generate()
        expected = self.expected_frame(self.work / "input.png")
        with Image.open(self.record / "image.png") as received:
            self.assertEqual(received.size, (512, 512))
            self.assertEqual(received.mode, expected.mode)
            self.assertEqual(received.tobytes(), expected.tobytes())

    def test_each_runtime_path_must_be_existing_and_absolute(self):
        for suffix in ("PYTHON", "AGENT", "MODEL"):
            key = f"{self.prefix}_{suffix}"
            for bad in ("relative/path", str(self.work / "missing")):
                with self.subTest(key=key, value=bad), self.assertRaisesRegex(RuntimeError, key):
                    self.generate(**{key: bad})
                self.assert_nothing_published()

    def test_unconfigured_runtime_is_refused_before_any_asset(self):
        with (
            patch.dict(os.environ, {"CAVI_GENERATION_PROVIDER": self.provider}, clear=True),
            self.assertRaisesRegex(RuntimeError, f"{self.prefix}_PYTHON"),
        ):
            generate(self.work, "input.png", "mesh.glb")
        self.assert_nothing_published()

    def test_resolution_is_refused(self):
        with (
            patch.dict(os.environ, self.settings("ok")),
            self.assertRaisesRegex(ValueError, "only to the TripoSR"),
        ):
            generate(self.work, "input.png", "mesh.glb", 128)
        self.assert_nothing_published()

    def test_agent_errors_are_reported_and_publish_nothing(self):
        for code, message in (
            ("model_unreadable", "No readable converted model config."),
            ("timeout", "Mesh generation exceeded 570 seconds."),
        ):
            with self.subTest(code=code), self.assertRaisesRegex(RuntimeError, f"{code}.*{message}"):
                self.generate("error", FAKE_AGENT_CODE=code, FAKE_AGENT_MESSAGE=message)
            self.assert_nothing_published()

    def test_a_crashing_agent_reports_its_exit_and_stderr(self):
        with self.assertRaisesRegex(RuntimeError, "exit 3.*backend crashed"):
            self.generate("crash")
        self.assert_nothing_published()

    def test_a_hung_agent_is_stopped_at_the_timeout(self):
        with (
            patch.dict(generation.PROVIDERS[self.provider], {"timeout": 3}),
            self.assertRaisesRegex(RuntimeError, "3 seconds"),
        ):
            self.generate("hang")
        self.assert_nothing_published()

    def test_unusable_results_publish_nothing(self):
        for mode, detail in (
            ("garbage", "no usable mesh result"),
            ("missing", "did not produce"),
            ("empty", "did not produce"),
            ("oversized", "500000"),
        ):
            with self.subTest(mode=mode), self.assertRaisesRegex(RuntimeError, detail):
                self.generate(mode)
            self.assert_nothing_published()

    def test_views_and_guides_need_trellis2(self):
        if generation.PROVIDERS[self.provider].get("guides"):
            self.skipTest("this provider accepts views and guides")
        (self.work / "guide.glb").write_bytes(b"glTF")
        for options in ({"views": ["input.png"]}, {"guide": "guide.glb"}, {"bbox": (1, 1, 1)}):
            with (
                self.subTest(options=options),
                patch.dict(os.environ, self.settings("ok")),
                self.assertRaisesRegex(ValueError, "only to the trellis2-mlx"),
            ):
                generate(self.work, "input.png", "mesh.glb", **options)
            self.assert_nothing_published()
        self.assertFalse((self.record / "image.png").exists())

    def test_a_competing_output_is_never_replaced(self):
        with self.assertRaises(FileExistsError):
            self.generate("race")
        self.assertEqual((self.work / "mesh.glb").read_bytes(), b"other-writer")


class Trellis2MlxTests(TripoSGMlxTests):
    provider, prefix, model, name = "trellis2-mlx", "CAVI_TRELLIS2_MLX", "trellis2", "TRELLIS.2"
    extra: ClassVar[dict] = {"vertex_colors": True}

    def expected_frame(self, image):
        return neural_worker.prepare_image(image, background=None, extent=512)

    def test_fast_draft_applies_and_enforces_face_cap(self):
        result = self.generate(quality="fast", FAKE_AGENT_QUALITY="fast")
        self.assertEqual(result["faces"], 166656)
        (self.work / "mesh.glb").unlink()
        with self.assertRaisesRegex(RuntimeError, "166666 faces"):
            self.generate("oversized", quality="fast", FAKE_AGENT_QUALITY="fast")
        self.assert_nothing_published()

    def test_high_quality(self):
        result = self.generate(quality="high", FAKE_AGENT_QUALITY="high")
        self.assertEqual((result["quality"], result["faces"]), ("high", 166_666))
        imported = inspect_glb(self.work, "mesh.glb")
        self.assertEqual((imported["vertices"], imported["triangles"]), (499_998, 166_666))

    def test_high_quality_refuses_a_glb_over_the_import_budget(self):
        with self.assertRaisesRegex(RuntimeError, "GLB cannot be imported.*geometry exceeds the import budget"):
            self.generate("over_budget_glb", quality="high", FAKE_AGENT_QUALITY="high")
        self.assert_nothing_published()

    def test_the_tool_schema_offers_the_high_tier(self):
        settings = {**self.settings("ok", FAKE_AGENT_QUALITY="high"), "CAVI_BLENDER_WORKSPACE": str(self.work)}
        with (
            patch.dict(os.environ, settings),
            patch.object(server, "call", side_effect=AssertionError("Unrelated scene accessed")),
        ):
            result = asyncio.run(server.mcp.call_tool("asset_io", {
                "action": "generate", "path": "mesh.glb", "image": "input.png", "quality": "high"}))
        self.assertIn('"quality":"high"', str(result).replace(" ", "").replace("'", '"'))
        self.assertTrue((self.work / "mesh.glb").is_file())

    def test_oversized_output_reports_actual_bytes(self):
        with self.assertRaisesRegex(RuntimeError, "67108865.*67108864"):
            self.generate("oversized_file")
        self.assert_nothing_published()

    def test_an_opaque_plain_background_reaches_the_agent_as_alpha(self):
        opaque = Image.new("RGB", (600, 400), (255, 255, 255))
        opaque.paste((40, 90, 160), (200, 100, 400, 300))
        opaque.save(self.work / "opaque.png")
        self.generate(image="opaque.png")
        with Image.open(self.record / "image.png") as received:
            self.assertEqual((received.size, received.mode), ((512, 512), "RGBA"))
            self.assertEqual(received.getpixel((0, 0))[3], 0)
            self.assertEqual(received.getpixel((256, 256)), (40, 90, 160, 255))

    def test_an_uncolored_checkpoint_publishes_a_mesh_without_vertex_colors(self):
        self.assertIs(self.generate("uncolored")["vertex_colors"], False)
        self.assertTrue((self.work / "mesh.glb").is_file())

    def test_a_result_without_the_color_flag_publishes_nothing(self):
        with self.assertRaisesRegex(RuntimeError, "no usable mesh result"):
            self.generate("unflagged")
        self.assert_nothing_published()

    def guided(self, **options):
        side = Image.new("RGBA", (300, 600), (0, 0, 0, 0))
        side.paste((20, 120, 60, 255), (50, 0, 250, 600))
        side.save(self.work / "side.png")
        (self.work / "guide.glb").write_bytes(b"glTF guide")
        with patch.dict(os.environ, self.settings("ok")):
            return generate(self.work, "input.png", "mesh.glb", **options)

    def test_views_and_a_guide_reach_the_agent_and_are_reported(self):
        report = self.guided(views=["side.png"], guide="guide.glb")
        expected = self.expected_frame(self.work / "side.png")
        with Image.open(self.record / "view-0.png") as received:
            self.assertEqual((received.size, received.tobytes()), ((512, 512), expected.tobytes()))
        self.assertEqual((self.record / "guide.glb").read_bytes(), b"glTF guide")
        self.assertEqual((report["views"], report["guided"]), (2, True))
        self.assertEqual(report["view_sha256"], [hashlib.sha256((self.work / "side.png").read_bytes()).hexdigest()])
        self.assertEqual(report["guide_sha256"], hashlib.sha256(b"glTF guide").hexdigest())
        self.assertTrue((self.work / "mesh.glb").is_file())

    def boxed(self, mode="ok", **options):
        with patch.dict(os.environ, self.settings(mode)):
            return generate(self.work, "input.png", "mesh.glb", **options)

    def test_a_bbox_reaches_the_agent_and_is_reported(self):
        self.assertEqual(self.boxed(bbox=(0.6, 0.6, 1.2))["bbox"], [0.6, 0.6, 1.2])
        self.assertTrue((self.work / "mesh.glb").is_file())
        (self.work / "mesh.glb").unlink()
        with self.assertRaisesRegex(RuntimeError, "no usable mesh result"):
            self.boxed("unboxed", bbox=(0.6, 0.6, 1.2))
        self.assert_nothing_published()

    def test_a_bbox_outside_the_contract_is_refused_before_the_agent(self):
        (self.work / "guide.glb").write_bytes(b"glTF guide")
        for options in ({"bbox": (1, 1)}, {"bbox": (1, 0, 1)}, {"bbox": (1, 1, 17)}, {"bbox": (True, 1, 1)},
                        {"bbox": (1, float("nan"), 1)}, {"bbox": (1, 1, 1), "guide": "guide.glb"}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "bbox takes"):
                self.boxed(**options)
            self.assert_nothing_published()
        self.assertFalse((self.record / "image.png").exists())

    def test_a_bbox_outside_the_glb_position_range_is_refused_before_the_agent(self):
        with patch.dict(os.environ, self.settings("ok")):
            for size in (1e-50, 1e40):
                path = f"mesh-{size}.glb"
                with self.subTest(size=size):
                    with self.assertRaisesRegex(ValueError, "bbox.*float32"):
                        generate(self.work, "input.png", path, bbox=(size, size, size))
                    self.assertFalse((self.work / path).exists())
                    self.assertFalse((self.record / "image.png").exists())

    def test_views_and_guides_outside_the_contract_are_refused_before_the_agent(self):
        for options, message in (
            ({"views": ["../side.png"]}, "Each view"),
            ({"views": ["guide.glb"]}, "Each view"),
            ({"views": ["side.png"] * 6}, "at most 5"),
            ({"guide": "side.png"}, "workspace GLB"),
            ({"guide": "missing.glb"}, "workspace GLB"),
        ):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, message):
                self.guided(**options)
            self.assert_nothing_published()
        self.assertFalse((self.record / "image.png").exists())

    def test_the_server_forwards_views_and_the_guide(self):
        settings = {**self.settings("ok"), "CAVI_BLENDER_WORKSPACE": str(self.work)}
        self.guided(views=["side.png"])
        (self.work / "mesh.glb").unlink()
        with (
            patch.dict(os.environ, settings),
            patch.object(server, "call", side_effect=AssertionError("Unrelated scene accessed")),
        ):
            report = asyncio.run(server.asset_io("generate", "mesh.glb", image="input.png", views=["side.png"],
                                                 guide="guide.glb"))
        self.assertEqual((report["views"], report["guided"]), (2, True))
        self.assertEqual((self.record / "guide.glb").read_bytes(), b"glTF guide")
