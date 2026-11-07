"""Reuse the rigged source fixture for face-level finish assignment."""
import os
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('vertex_edit_fixture.py')))
finish=bpy.data.materials.new('TrimFinish')
finish.diffuse_color=(.7,.35,.08,1)
bpy.ops.wm.save_as_mainfile(filepath=str(Path(os.environ['CAVI_BLENDER_WORKSPACE'])/'initial.blend'),
                          check_existing=False)
