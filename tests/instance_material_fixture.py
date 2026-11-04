"""A shared-mesh kit and exact 16-bit color, roughness and normal maps."""

import os
import runpy
import struct
import zlib
from pathlib import Path

root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
runpy.run_path(str(Path(__file__).with_name('collection_assembly_fixture.py')))


def chunk(kind, payload):
    return struct.pack('>I', len(payload))+kind+payload+struct.pack('>I', zlib.crc32(kind+payload))


for name, rgb in [('color', (12001, 23003, 41011)), ('roughness', (10001, 10001, 10001)),
                  ('normal', (32768, 32768, 65535))]:
    row = b'\0'+struct.pack('>HHH', *rgb)*2
    (root/(name+'.png')).write_bytes(b'\x89PNG\r\n\x1a\n'+
        chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 16, 2, 0, 0, 0))+
        chunk(b'IDAT', zlib.compress(row*2))+chunk(b'IEND', b''))
