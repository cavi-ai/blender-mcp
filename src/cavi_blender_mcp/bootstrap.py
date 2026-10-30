"""Package-local Blender entry point used by runtime start."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import bpy

    from cavi_blender_mcp.blender_bridge import register, serve_background

    register()
    if bpy.app.background:
        serve_background()


if __name__ == "__main__":
    main()
