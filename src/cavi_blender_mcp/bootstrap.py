"""Package-local Blender entry point used by runtime start."""

import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from cavi_blender_mcp.blender_bridge import register

    register()


if __name__ == "__main__":
    main()
