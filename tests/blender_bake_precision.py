"""Native bake precision, normal convention and data/color encoding checks."""
import json
import math
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
root = Path(sys.argv[sys.argv.index('--') + 1]) if '--' in sys.argv else Path(folder.name)
root.mkdir(parents=True, exist_ok=True)
bridge._workspace = root
state = bridge.dispatch('session_control', {'action': 'inspect'})
lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'precision-fixture',
                                          'expected_project': state['project_id']})['lease_id']


def bake(path, **changes):
    return bridge.dispatch('owned_edit', {'operation': 'bake_map', 'params': {
        'lease_id': lease, 'map': 'normal', 'name': 'PrecisionLow', 'path': path,
        'high': ['PrecisionHigh'], 'resolution': 64, 'samples': 1, 'margin': 0,
        'cage_extrusion': .2, 'max_ray_distance': .5, **changes}})


def pixels(path):
    image = bpy.data.images.load(str(path))
    try:
        image.colorspace_settings.name = 'Non-Color'
        values = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(values)
        return values.reshape(-1, 4)[:, :3]
    finally:
        bpy.data.images.remove(image)


try:
    bpy.ops.mesh.primitive_plane_add(size=2)
    bpy.context.object.name = 'PrecisionLow'
    n = 17
    vertices = [(-1 + x * 2 / (n - 1), -1 + y * 2 / (n - 1),
                 .04 * math.sin(x * .4) * math.cos(y * .35))
                for y in range(n) for x in range(n)]
    faces = [(y * n + x, y * n + x + 1, (y + 1) * n + x + 1, (y + 1) * n + x)
             for y in range(n - 1) for x in range(n - 1)]
    mesh = bpy.data.meshes.new('Relief')
    mesh.from_pydata(vertices, [], faces)
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    high = bpy.data.objects.new('PrecisionHigh', mesh)
    bpy.context.scene.collection.objects.link(high)
    scene = bpy.context.scene
    settings = scene.render.bake
    settings.normal_r, settings.normal_g, settings.normal_b = 'NEG_Z', 'NEG_X', 'NEG_Y'
    scene.view_settings.exposure = 3
    scene.view_settings.gamma = 1.7
    scene.render.image_settings.file_format = 'JPEG'
    source_state = (settings.normal_r, settings.normal_g, settings.normal_b,
                    scene.view_settings.view_transform, scene.view_settings.exposure,
                    scene.view_settings.gamma, scene.render.image_settings.file_format)
    counts = tuple(len(items) for items in (bpy.data.scenes, bpy.data.images,
                                           bpy.data.materials, bpy.data.objects, bpy.data.meshes))
    result = bake('normal-default.png')
    header = (root / 'normal-default.png').read_bytes()[:26]
    assert header[24] == 16, f'Native bake silently encoded {header[24]}-bit PNG'
    assert result['bit_depth'] == 16
    values = pixels(root / 'normal-default.png')
    assert values[:, 2].min() > .9, 'Normal channels inherited scene swizzles or view transforms'
    assert len(np.unique(values[:, :2])) > 256, 'Bake was quantized before 16-bit encoding'
    explicit = bake('normal-8.png', bit_depth=8)
    assert explicit['bit_depth'] == (root / 'normal-8.png').read_bytes()[24] == 8
    assert tuple(len(items) for items in (bpy.data.scenes, bpy.data.images,
                                        bpy.data.materials, bpy.data.objects, bpy.data.meshes)) == counts
    assert source_state == (settings.normal_r, settings.normal_g, settings.normal_b,
                            scene.view_settings.view_transform, scene.view_settings.exposure,
                            scene.view_settings.gamma, scene.render.image_settings.file_format)

    from cavi_blender_mcp.blender_bake import write_png

    ramp = bpy.data.images.new('Precision Ramp', 2, 1, alpha=False, float_buffer=True, is_data=True)
    raw = np.array([[.123456, .456789, .987654], [.000321, .333333, .765432]], np.float32)
    rgba = np.column_stack([raw, np.ones(2, np.float32)])
    ramp.pixels.foreach_set(rgba.ravel())
    try:
        for depth in (8, 16):
            path = root / f'data-{depth}.png'
            write_png(ramp, path, depth, 'normal')
            assert path.read_bytes()[24] == depth
            np.testing.assert_allclose(pixels(path), raw, atol=1 / ((1 << depth) - 1), rtol=0)
        # Lightmap samples start scene-linear and must receive only the sRGB transfer.
        ramp.colorspace_settings.name = 'Linear Rec.709'
        # Changing a generated image's color-space label reloads its buffer.
        ramp.pixels.foreach_set(rgba.ravel())
        np.testing.assert_allclose(np.asarray(ramp.pixels).reshape(-1, 4)[:, :3], raw)
        path = root / 'color-16.png'
        write_png(ramp, path, 16, 'lightmap')
        expected = np.where(raw <= .0031308, raw * 12.92, 1.055 * raw ** (1 / 2.4) - .055)
        np.testing.assert_allclose(pixels(path), expected, atol=2 / 65535, rtol=0)
    finally:
        bpy.data.images.remove(ramp)
    (root / 'native.json').write_text(json.dumps({'passed': True, 'default': result,
        'explicit': explicit, 'unique_normal_samples': len(np.unique(values[:, :2])),
        'state_restored': True, 'data_and_srgb_ramps': True}, indent=2) + '\n')
    print('Native bake precision, explicit encoding, color transfer and state restoration passed')
finally:
    bridge.dispatch('session_control', {'action': 'release', 'lease_id': lease})
    folder.cleanup()
