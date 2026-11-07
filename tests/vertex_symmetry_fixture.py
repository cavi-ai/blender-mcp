"""Keep unilateral morphs and a small existing base-mesh asymmetry."""
import os
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('vertex_edit_fixture.py')))
bpy.data.objects['Static'].data.vertices[4].co.x += .0001
bpy.ops.wm.save_as_mainfile(filepath=str(Path(os.environ['CAVI_BLENDER_WORKSPACE'])/'initial.blend'),
                           check_existing=False)
