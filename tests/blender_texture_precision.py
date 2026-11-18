"""Run with Blender --background --python-exit-code 1 --python tests/blender_texture_precision.py."""
import struct
import sys
import tempfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import bpy
import numpy as np

from cavi_blender_mcp.blender_export import sidecar_copy

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    # File-backed byte sRGB pixels are already encoded, including alpha.
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    rgba = bytes([32, 48, 112, 127, 251, 215, 172, 255, 27, 88, 149, 0])
    payload = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 3, 1, 8, 6, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(b'\x00' + rgba)) + chunk(b'IEND', b''))
    (root / 'byte-source.png').write_bytes(payload)
    byte_source = bpy.data.images.load(str(root / 'byte-source.png'))
    assert not byte_source.is_float and byte_source.colorspace_settings.name == 'sRGB'
    byte_copy = sidecar_copy(byte_source, root / 'byte-copy.png')
    assert (root / 'byte-copy.png').read_bytes()[24:26] == bytes([8, 6])
    np.testing.assert_array_equal(byte_copy.pixels[:], byte_source.pixels[:])
    image = bpy.data.images.new('FloatSource', 2, 2, alpha=True, float_buffer=True)
    image.colorspace_settings.name = 'Non-Color'
    image.pixels[:] = [.123456, .234567, .345678, 1] * 4
    copy = sidecar_copy(image, root / 'float.png')
    assert (root / 'float.png').read_bytes()[24] == 16
    loaded = bpy.data.images.load(str(root / 'float.png'))
    loaded.colorspace_settings.name = 'Non-Color'
    second = sidecar_copy(loaded, root / 'loaded.png')
    assert (root / 'loaded.png').read_bytes()[24] == 16
    reopened = bpy.data.images.load(str(root / 'loaded.png'))
    reopened.colorspace_settings.name = 'Non-Color'
    np.testing.assert_allclose(reopened.pixels[:], loaded.pixels[:], atol=1/65535)
    # Color images also survive a second export without a double sRGB decode.
    color = bpy.data.images.new('ColorSource', 2, 2, alpha=True, float_buffer=True)
    color.pixels[:] = [.123456, .234567, .345678, 1] * 4
    first_color = sidecar_copy(color, root / 'color.png')
    next_color = sidecar_copy(first_color, root / 'color-again.png')
    np.testing.assert_allclose(next_color.pixels[:], first_color.pixels[:], atol=2/65535)
    image.pixels[0] = 2
    try:
        sidecar_copy(image, root / 'hdr.png')
    except ValueError:
        pass
    else:
        raise AssertionError('HDR source was silently clipped')
    print('PNG16 source samples survive export and reload; HDR clipping rejected')
