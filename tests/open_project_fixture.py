"""Saved sources for the private project-switch MCP case."""
import os
from pathlib import Path

import bpy

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
bpy.context.preferences.filepaths.save_version = 0
bpy.data.objects['Cube'].name = 'SourceProp'
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'source.blend'), check_existing=False)
bpy.data.objects['SourceProp'].name = 'TargetProp'
text = bpy.data.texts.new('autorun.py')
text.use_module = True
text.write(f'from pathlib import Path\nPath({str(root / "autorun-ran")!r}).touch()\n')
bpy.ops.wm.save_as_mainfile(filepath=str(root / 'target.blend'), check_existing=False)
bpy.ops.wm.open_mainfile(filepath=str(root / 'source.blend'), load_ui=False, use_scripts=False)
