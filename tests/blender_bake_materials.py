"""Native multi-material bake targets must never write source image buffers."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge


def fixture():
    mesh = bpy.data.meshes.new('PaintedLow')
    mesh.from_pydata([(-1, -.5, 0), (-.1, -.5, 0), (-.1, .5, 0), (-1, .5, 0),
                      (.1, -.5, 0), (1, -.5, 0), (1, .5, 0), (.1, .5, 0)],
                     [], [(0, 1, 2, 3), (4, 5, 6, 7)])
    uv = mesh.uv_layers.new(name='BakeUV')
    for loop, point in zip(uv.data, [(.05, .1), (.45, .1), (.45, .9), (.05, .9),
                                    (.55, .1), (.95, .1), (.95, .9), (.55, .9)]):
        loop.uv = point
    low = bpy.data.objects.new('PaintedLow', mesh)
    bpy.context.scene.collection.objects.link(low)
    materials, images = [], []
    for i in range(3):
        image = bpy.data.images.new(f'OriginalPaint{i}', 64, 64, alpha=False,
                                    float_buffer=True, is_data=True)
        color = [(.11 + i * .1), (.22 + i * .1), (.33 + i * .1), 1.]
        image.pixels.foreach_set(color * (64 * 64))
        material = bpy.data.materials.new(f'OriginalMaterial{i}')
        material.use_nodes = True
        node = material.node_tree.nodes.new('ShaderNodeTexImage')
        node.image = image
        material.node_tree.nodes.active = node
        materials.append(material)
        images.append(image)
    mesh.materials.append(materials[0])
    mesh.materials.append(materials[1])
    low.material_slots[1].link = 'OBJECT'
    low.material_slots[1].material = materials[2]
    mesh.polygons[1].material_index = 1
    twin = low.copy()
    twin.name = 'PaintedLinkedCopy'
    twin.location.z = -3
    bpy.context.scene.collection.objects.link(twin)
    high_mesh = bpy.data.meshes.new('BakeHigh')
    high_mesh.from_pydata([(-1.1, -.6, .05), (1.1, -.6, .05),
                           (1.1, .6, .05), (-1.1, .6, .05)], [], [(0, 1, 2, 3)])
    high = bpy.data.objects.new('BakeHigh', high_mesh)
    bpy.context.scene.collection.objects.link(high)
    return low, twin, materials, images


def snapshot(values):
    low, twin, materials, images = values
    buffers = {}
    for image in images:
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        buffers[image.name] = hashlib.sha256(pixels.tobytes()).hexdigest()
    return {
        'buffers': buffers,
        'slots': {o.name: [(slot.link, slot.material.name if slot.material else None) for slot in o.material_slots]
                  for o in (low, twin)},
        'mesh': {'vertices': [tuple(v.co) for v in low.data.vertices],
                 'polygons': [(tuple(p.vertices), p.material_index) for p in low.data.polygons],
                 'uvs': [tuple(p.uv) for p in low.data.uv_layers[0].data],
                 'users': low.data.users, 'shared': low.data == twin.data},
        'nodes': {m.name: {'active': m.node_tree.nodes.active.name if m.node_tree.nodes.active else None,
                           'nodes': sorted((n.name, n.type) for n in m.node_tree.nodes),
                           'links': sorted((l.from_node.name, l.to_node.name) for l in m.node_tree.links)}
                  for m in materials},
        'resources': {name: sorted(item.name for item in getattr(bpy.data, name))
                      for name in ('objects', 'meshes', 'materials', 'images', 'scenes')},
        'selected': sorted(o.name for o in bpy.context.selected_objects),
        'active': str(bpy.context.view_layer.objects.active),
        'active_material': low.active_material_index,
        'visibility': {o.name: [o.hide_render, o.hide_viewport, o.hide_get()]
                       for o in bpy.context.scene.objects},
    }


def check_output(path):
    image = bpy.data.images.load(str(path))
    try:
        image.colorspace_settings.name = 'Non-Color'
        pixels = np.array(image.pixels[:], np.float32).reshape(64, 64, 4)
        # Sample interior pixels on each material's UV island.
        for column in (16, 48):
            np.testing.assert_allclose(pixels[32, column, :3], [.5, .5, 1.], atol=.01)
    finally:
        bpy.data.images.remove(image)


def main():
    folder = tempfile.TemporaryDirectory()
    root = Path(sys.argv[sys.argv.index('--') + 1]) if '--' in sys.argv else Path(folder.name)
    root.mkdir(parents=True, exist_ok=True)
    bridge._workspace = root
    values = fixture()
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'material-fixture',
        'expected_project': state['project_id']})['lease_id']
    try:
        def run_case(filename):
            before = snapshot(values)
            result = bridge.dispatch('owned_edit', {'operation': 'bake_png', 'params': {
                'map': 'normal', 'name': 'PaintedLow', 'path': filename, 'high': ['BakeHigh'],
                'resolution': 64, 'samples': 1, 'margin': 0, 'uv_layer': 'BakeUV',
                'cage_extrusion': .1, 'max_ray_distance': .2, 'lease_id': lease}})
            after = snapshot(values)
            (root / (filename + '.state.json')).write_text(
                json.dumps({'before': before, 'after': after}, indent=2))
            assert before['buffers'] == after['buffers'], 'Bake changed original source image buffers'
            assert before == after, 'Bake changed source materials, geometry, sharing or selection'
            check_output(root / filename)
            return result

        result = run_case('normal.png')
        for material in values[2]:
            for node in list(material.node_tree.nodes):
                if node.type == 'TEX_IMAGE':
                    material.node_tree.nodes.remove(node)
        run_case('no-image-nodes.png')
        values[0].material_slots[0].material = None
        run_case('empty-slot.png')
        before = snapshot(values)
        try:
            run_case('normal.png')
            raise AssertionError('Existing output was overwritten')
        except FileExistsError:
            pass
        assert snapshot(values) == before, 'Failed bake changed source state or retained resources'
        print(json.dumps({'native_multi_material': 'passed', 'source_unchanged': True,
                           'both_islands_baked': True, 'empty_and_untextured_slots': True,
                           'failure_cleanup': True, 'result': result}))
    finally:
        bridge.dispatch('session_control', {'action': 'release', 'lease_id': lease})
        folder.cleanup()


if __name__ == '__main__':
    main()
