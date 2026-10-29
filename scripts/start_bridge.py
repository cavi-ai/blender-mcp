"""Run with Blender --python scripts/start_bridge.py in a dedicated session."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp.blender_bridge import register

register()
