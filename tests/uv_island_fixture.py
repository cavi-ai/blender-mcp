"""Unmarked UV discontinuities and a one-float32-ULP chart boundary."""
import os
import runpy
import struct
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('vertex_edit_fixture.py')))
mesh=bpy.data.objects['TileGrid'].data
layer=mesh.uv_layers.new(name='NearContinuous')
for target,source in zip(layer.data,mesh.uv_layers['Continuous'].data,strict=True):
    target.uv=source.uv
bits=struct.unpack('<I',struct.pack('<f',layer.data[4].uv.x))[0]
layer.data[4].uv.x=struct.unpack('<f',struct.pack('<I',bits+1))[0]
mesh.uv_layers.active_index=1
assert not next(e for e in mesh.edges if set(e.vertices)=={1,2}).use_seam
bpy.ops.wm.save_as_mainfile(filepath=str(Path(os.environ['CAVI_BLENDER_WORKSPACE'])/'initial.blend'))
