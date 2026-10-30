import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cavi_blender_mcp.generation import generate


class GenerationTests(unittest.TestCase):
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

            def complete(command, **kwargs):
                Path(command[3]).write_bytes(b"generated-glb")
                return SimpleNamespace(returncode=0, stdout='{"triangles": 12}', stderr="")

            with self.configured(work), patch("subprocess.run", side_effect=complete):
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
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired("worker", 180)),
                self.assertRaisesRegex(RuntimeError, "180 seconds"),
            ):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertFalse((work / "mesh.glb").exists())
            self.assertFalse(list(work.glob(".cavi-generation-*")))

    def test_worker_failure_reports_exit_and_preserves_diagnostics(self):
        for code, stderr, stdout, detail in (
            (-9, "", "", "No worker diagnostics"),
            (2, " import failed ", "", "import failed"),
            (3, " ", "encoder stopped", "encoder stopped"),
        ):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as root:
                work = Path(root)
                (work / "input.png").write_bytes(b"input")

                def fail(command, exit_code=code, worker_stdout=stdout, worker_stderr=stderr, **kwargs):
                    Path(command[3]).write_bytes(b"partial-glb")
                    return SimpleNamespace(returncode=exit_code, stdout=worker_stdout, stderr=worker_stderr)

                with (
                    self.configured(work),
                    patch("subprocess.run", side_effect=fail),
                    self.assertRaisesRegex(RuntimeError, f"exit {code}.*{detail}"),
                ):
                    generate(work, "input.png", "mesh.glb", 128)
                self.assertFalse((work / "mesh.glb").exists())
                self.assertFalse(list(work.glob(".cavi-generation-*")))

    def test_a_competing_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as root:
            work = Path(root)
            (work / "input.png").write_bytes(b"input")

            def race(command, **kwargs):
                Path(command[3]).write_bytes(b"generated-glb")
                (work / "mesh.glb").write_bytes(b"other-writer")
                return SimpleNamespace(returncode=0, stdout="{}", stderr="")

            with (
                self.configured(work),
                patch("subprocess.run", side_effect=race),
                self.assertRaises(FileExistsError),
            ):
                generate(work, "input.png", "mesh.glb", 128)
            self.assertEqual((work / "mesh.glb").read_bytes(), b"other-writer")
