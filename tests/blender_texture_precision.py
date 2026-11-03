"""Run with Blender --background --python-exit-code 1 --python tests/blender_texture_precision.py."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import bpy
import numpy as np

from cavi_blender_mcp.blender_export import sidecar_copy

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
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
