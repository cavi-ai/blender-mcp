"""Package the bridge as a Blender extension that loads this installed server package."""

import importlib.metadata
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path

from .runtime import blender_executable

ID = "cavi_blender_mcp"
PACKAGE = Path(__file__).resolve().parent
MANIFEST = """schema_version = "1.0.0"
id = "{id}"
version = "{version}"
name = "CAVI Blender MCP"
tagline = "Serve MCP tool calls from this Blender session"
maintainer = "CAVI AI"
type = "add-on"
website = "https://cavi-ai.xyz/docs/blender-mcp"
license = ["SPDX:MIT"]
blender_version_min = "5.2.0"

[permissions]
network = "Accept tool calls from the local MCP server"
files = "Open, save and export files in the bridge workspace"
"""
# The extension holds no bridge code: it loads the server's installed package, so the bridge
# build identity always matches the server that built it.
ENTRY = '''"""Start the CAVI Blender MCP bridge from the installed server package."""

import importlib.util
from pathlib import Path

PACKAGE = Path({package!r})


def _controls():
    if not (PACKAGE / "bootstrap.py").is_file():
        raise ImportError(f"{{PACKAGE}} is missing; reinstall with cavi-blender-mcp extension install")
    spec = importlib.util.spec_from_file_location("cavi_blender_mcp_bootstrap",
                                                  PACKAGE / "bootstrap.py")
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    bootstrap.load_package()
    from cavi_blender_mcp import blender_extension

    return blender_extension


def register():
    _controls().register()


def unregister():
    _controls().unregister()
'''


def version():
    """The server release as the semantic version Blender manifests require."""
    return re.match(r"\d+\.\d+\.\d+", importlib.metadata.version("cavi-blender-mcp")).group()


def build(output):
    """Write ``cavi_blender_mcp-<version>.zip`` into ``output``; an existing archive is refused."""
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{ID}-{version()}.zip"
    with zipfile.ZipFile(archive, "x") as bundle:
        bundle.writestr("blender_manifest.toml", MANIFEST.format(id=ID, version=version()))
        bundle.writestr("__init__.py", ENTRY.format(package=str(PACKAGE)))
    return archive


def install():
    """Install and enable the extension in Blender's ``user_default`` repository."""
    blender = blender_executable()
    with tempfile.TemporaryDirectory() as temporary:
        archive = build(temporary)
        result = subprocess.run([blender, "--command", "extension", "install-file",
                                 "--repo", "user_default", "--enable", str(archive)],
                                check=False, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"Blender could not install the extension: {reason}")
    return {"installed": ID, "version": version(), "package": str(PACKAGE), "blender": blender}
