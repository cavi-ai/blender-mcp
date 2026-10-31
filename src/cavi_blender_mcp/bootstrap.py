"""Package-local Blender entry point used by runtime start."""

import importlib.util
import sys
from pathlib import Path

PACKAGE = "cavi_blender_mcp"


def load_package():
    # Server site-packages hold extensions built for another Python ABI.
    if PACKAGE in sys.modules:
        return sys.modules[PACKAGE]
    folder = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location(
        PACKAGE, folder / "__init__.py", submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


def main():
    import bpy

    load_package()
    from cavi_blender_mcp.blender_bridge import register, serve_background

    register()
    if bpy.app.background:
        serve_background()


if __name__ == "__main__":
    main()
