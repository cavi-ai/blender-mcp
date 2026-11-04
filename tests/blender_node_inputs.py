"""Native source persistence, current-frame snapshots and lossless refusal of instances."""

import json
import runpy
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

runpy.run_path(str(Path(__file__).with_name('procedural_asset_fixture.py')))
with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'node-input-check',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    def inspect():
        return bridge.dispatch('inspect_geometry_nodes', {'name': 'Fence'})['modifiers'][0]

    inputs = {s['name']: s['identifier'] for s in inspect()['inputs']}
    edit('set_geometry_inputs', name='Fence', modifier='Generator', inputs={inputs['Count']: 5,
        inputs['Finish']: {'name': 'Gold', 'id_type': 'MATERIAL'}})
    source = bpy.data.objects['Fence']
    tree = source.modifiers[0].node_group
    bpy.context.scene.frame_set(4, subframe=.25)
    snapshot = edit('snapshot_geometry', name='Fence', new_name='Fence_LOD0')
    assert snapshot['frame'] == 4.25
    assert snapshot['triangles'] == 60, snapshot
    assert next(s for s in snapshot['material_triangles'] if s['material'] == 'Gold')['triangles'] == 60, snapshot
    assert source.modifiers[0].node_group == tree and not source.data.vertices
    assert bpy.data.objects['Fence_LOD0'].data != source.data
    assert all(abs(v.value-.25) < 1e-6 for v in bpy.data.objects['Fence_LOD0'].data.attributes['AuthoredMask'].data)
    # A graph containing instances must not silently become an empty/partial mesh.
    sink = next(n for n in tree.nodes if n.type == 'GROUP_OUTPUT')
    link = sink.inputs[0].links[0]
    previous = link.from_socket
    instances = next(n for n in tree.nodes if n.bl_idname == 'GeometryNodeInstanceOnPoints')
    tree.links.new(instances.outputs[0], sink.inputs[0])
    bpy.context.view_layer.update()
    objects, meshes = set(bpy.data.objects), set(bpy.data.meshes)
    try:
        edit('snapshot_geometry', name='Fence', new_name='LostInstances')
    except ValueError as exc:
        assert 'unrealized instances' in str(exc), exc
    else:
        raise AssertionError('Snapshot silently discarded instances')
    assert objects == set(bpy.data.objects) and meshes == set(bpy.data.meshes)
    tree.links.new(previous, sink.inputs[0])
    bpy.context.view_layer.update()
    path = Path(folder)/'editable.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(path))
    bpy.ops.wm.open_mainfile(filepath=str(path))
    saved = inspect()
    assert next(s for s in saved['inputs'] if s['name'] == 'Count')['value'] == 5
    assert bpy.data.objects['Fence'].modifiers[0].node_group == bpy.data.objects['OtherFence'].modifiers[0].node_group
    assert not bpy.data.objects['Fence_LOD0'].modifiers
    print(json.dumps({'blender': bpy.app.version_string, 'saved_count': 5,
                      'snapshot_triangles': 60, 'unrealized_instances_rejected': True}))
