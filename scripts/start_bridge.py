"""Run with Blender --python scripts/start_bridge.py in a dedicated session."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp.blender_bridge import register, serve_background

register()
if bpy.app.background:
    serve_background()
