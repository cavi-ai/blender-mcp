"""Source distributions contain public project files and exclude local scratch."""

import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DistributionTests(unittest.TestCase):
    def test_sdist_excludes_untracked_scratch_and_keeps_source_inputs(self):
        with (
            tempfile.TemporaryDirectory(prefix=".packaging-private-", dir=ROOT) as scratch,
            tempfile.TemporaryDirectory() as output,
        ):
            (Path(scratch) / "private.txt").write_text("local scratch must not ship")
            built = subprocess.run(
                ["uv", "build", "--sdist", "--out-dir", output],
                cwd=ROOT, capture_output=True, text=True, check=False,
            )
            self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            with tarfile.open(next(Path(output).glob("*.tar.gz"))) as archive:
                paths = {Path(*Path(item).parts[1:]) for item in archive.getnames()}
            self.assertFalse(any(Path(scratch).name in path.parts for path in paths))
            self.assertTrue({
                Path("src/cavi_blender_mcp/server.py"),
                Path("scripts/docs/build.py"),
                Path("tests/test_distribution.py"),
                Path("evals/core.manifest.json"),
                Path("examples/material-texture-sets/README.md"),
                Path("docs/blender-mcp/source/pages/introduction/overview.md"),
                Path("requirements-neural.txt"),
                Path("requirements-triposg.txt"),
                Path("pyproject.toml"),
                Path("README.md"),
                Path("LICENSE"),
            } <= paths)


if __name__ == "__main__":
    unittest.main()
