"""Blender scene tools over MCP."""

import importlib.util
import sys
from pathlib import Path

CORE = "cavi_mcp_core"


def _core_folders():
    here = Path(__file__).resolve().parent
    # An installed wheel sits beside MCP Core; a source checkout keeps it in the project venv.
    yield here.parent / CORE
    yield from sorted(here.parents[1].glob(f".venv/lib/python*/site-packages/{CORE}"))


def _load_core():
    """Blender's Python cannot read the server's site-packages, so the bridge loads the
    server's installed MCP Core by path; its workspace and files modules use only the
    standard library."""
    if CORE in sys.modules or importlib.util.find_spec(CORE) is not None:
        return
    for folder in _core_folders():
        if (folder / "__init__.py").is_file():
            spec = importlib.util.spec_from_file_location(
                CORE, folder / "__init__.py", submodule_search_locations=[str(folder)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[CORE] = module
            spec.loader.exec_module(module)
            return
    raise ImportError(f"{CORE} must be installed beside {Path(__file__).resolve().parent}")


_load_core()
