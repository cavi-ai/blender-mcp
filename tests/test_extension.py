"""The Blender extension archive loads this installed server package."""
import ast
import io
import json
import re
import tempfile
import tomllib
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path

import cavi_blender_mcp
from cavi_blender_mcp.cli import main


class ExtensionBuildTests(unittest.TestCase):
    def build(self, folder):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["extension", "build", "--output", folder])
        return code, json.loads(output.getvalue())

    def test_archive_points_at_the_installed_package_and_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            code, result = self.build(folder)
            self.assertEqual(code, 0)
            with zipfile.ZipFile(result["archive"]) as bundle:
                self.assertEqual(sorted(bundle.namelist()), ["__init__.py", "blender_manifest.toml"])
                manifest = tomllib.loads(bundle.read("blender_manifest.toml").decode())
                entry = ast.parse(bundle.read("__init__.py").decode())
            self.assertEqual((manifest["id"], manifest["type"]), ("cavi_blender_mcp", "add-on"))
            self.assertRegex(manifest["version"], r"^\d+\.\d+\.\d+$")
            self.assertEqual(Path(result["archive"]).name, f"cavi_blender_mcp-{manifest['version']}.zip")
            self.assertEqual(set(manifest["permissions"]), {"network", "files"})
            package = next(node.value.args[0].value for node in entry.body
                           if isinstance(node, ast.Assign) and node.targets[0].id == "PACKAGE")
            self.assertEqual(Path(package), Path(cavi_blender_mcp.__file__).resolve().parent)
            before = Path(result["archive"]).read_bytes()
            code, refused = self.build(folder)
            self.assertEqual(code, 1)
            self.assertTrue(re.search("exists", refused["reason"]), refused)
            self.assertEqual(Path(result["archive"]).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
