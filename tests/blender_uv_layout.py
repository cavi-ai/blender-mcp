"""Native UV preflight fixtures and read-only guarantees."""
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge


def quad(name, left=.1, right=.4):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [], [(0, 1, 2, 3)])
    layer = mesh.uv_layers.new(name='BakeUV')
    for loop, uv in zip(layer.data, [(left, .1), (right, .1), (right, .4), (left, .4)]):
        loop.uv = uv
    # The render-active layer deliberately differs from exported UV0.
    other = mesh.uv_layers.new(name='RenderUV')
    for loop in other.data:
        loop.uv = (.5, .5)
    other.active_render = True
    value = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(value)
    return value


a, b, c = quad('Clean'), quad('Stacked'), quad('Separate', .5, .8)
a.modifiers.new('Unevaluated', 'SUBSURF')
state = bridge.dispatch('session_control', {'action': 'inspect'})
lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'other-editor',
                                          'expected_project': state['project_id']})


def snapshot():
    return json.dumps({
        'dirty': bpy.data.is_dirty, 'active': str(bpy.context.view_layer.objects.active),
        'selected': sorted(o.name for o in bpy.context.selected_objects),
        'meshes': {o.name: {'vertices': [tuple(v.co) for v in o.data.vertices],
                            'faces': [tuple(p.vertices) for p in o.data.polygons],
                            'uvs': [[tuple(v.uv) for v in layer.data] for layer in o.data.uv_layers],
                            'active_uv': o.data.uv_layers.active_index,
                            'render_uv': [uv.active_render for uv in o.data.uv_layers]}
                   for o in (a, b, c)},
        'counts': [len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.materials)],
    }, sort_keys=True)


before = snapshot()
params = {'texture_resolution': [100, 100], 'padding_pixels': 2}
clean = bridge.dispatch('inspect_uv_layout', {**params, 'names': [a.name, c.name]})
assert clean['complete'] and clean['unique_tile_ready'], clean
assert clean['charts'] == 2
assert clean['objects'][0]['uv_layer_index'] == 0
assert clean['objects'][0]['unevaluated_modifiers'] == ['SUBSURF']
stacked = bridge.dispatch('inspect_uv_layout', {**params, 'names': [a.name, b.name]})
assert not stacked['unique_tile_ready'] and stacked['overlap']['triangle_pairs'] == 2
named = bridge.dispatch('inspect_uv_layout', {**params, 'names': [a.name], 'uv_layer': 'RenderUV'})
assert named['degenerate_triangles'] == 2 and not named['unique_tile_ready']
bounded = bridge.dispatch('inspect_uv_layout', {**params, 'names': [a.name, b.name],
                                              'comparison_budget': 1})
assert not bounded['complete'] and not bounded['unique_tile_ready']
for changes in ({'names': [a.name, a.name]}, {'uv_layer': 'Missing'}, {'padding_pixels': -1}):
    try:
        bridge.dispatch('inspect_uv_layout', {**params, 'names': [a.name], **changes})
        raise AssertionError('Invalid UV inspection was accepted')
    except ValueError:
        pass
assert snapshot() == before, 'Inspection changed source or selection state'
after = bridge.dispatch('session_control', {'action': 'inspect'})
assert after['owner'] == 'other-editor' and after['active']
bridge.dispatch('session_control', {'action': 'release', 'lease_id': lease['lease_id']})
print(json.dumps({'native_uv_layout': 'passed', 'source_unchanged': True,
                  'clean': clean, 'stacked': stacked, 'budget': bounded}))
