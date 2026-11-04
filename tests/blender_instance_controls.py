"""Definition inspection is read-only; shared procedural overrides survive reopen."""

import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp.blender_asset_library import ids

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('instance_controls_fixture.py')))
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'instance-controls-context',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    source = bridge.dispatch('inspect_asset_library', {'path': 'kit.blend'})
    loaded = edit('append_asset_library_instances', path='kit.blend', names=['ProceduralKit'], expected_sha256=source['sha256'])
    a = loaded['instances'][0]['name']
    edit('duplicate_object', name=a, new_name='Kit_B', linked=True)
    fence = next(i['name'] for i in loaded['items'] if i['source_name'] == 'Fence' and i['id_type'] == 'OBJECT')
    before = ids(), bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    inventory = bridge.dispatch('inspect_collection_instance', {'name': a})
    inspected = bridge.dispatch('inspect_instance_geometry_nodes', {'name': fence, 'instance': a})
    assert before == (ids(), bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    count = next(s['identifier'] for s in inspected['modifiers'][0]['inputs'] if s['name'] == 'Count')
    edit('set_instance_geometry_inputs', name=fence, instance=a, modifier='Generator', inputs={count: 7})
    assert before == (ids(), bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    consumer = root/'consumer.blend'
    edit('save_project', path='consumer.blend')
    assert not bpy.data.is_dirty
    for operation, params in [('inspect_collection_instance', {'name': a}),
                              ('inspect_instance_geometry_nodes', {'name': fence, 'instance': a})]:
        bridge.dispatch(operation, params)
        assert not bpy.data.is_dirty
    bpy.ops.wm.open_mainfile(filepath=str(consumer))
    assert bpy.data.objects[a].instance_collection == bpy.data.objects['Kit_B'].instance_collection
    assert fence not in bpy.context.scene.objects
    reopened = bridge.dispatch('inspect_instance_geometry_nodes', {'name': fence, 'instance': 'Kit_B'})
    assert next(s['value'] for s in reopened['modifiers'][0]['inputs'] if s['name'] == 'Count') == 7
    assert reopened['modifiers'][0]['node_group'] == inspected['modifiers'][0]['node_group']
    assert inventory['instance_collection'] == reopened['definition']
    print(json.dumps({'blender': bpy.app.version_string, 'inspection_kept_clean_file': True,
        'definition_edit_preserved_context_and_ids': True, 'shared_override_survived_reopen': 7,
        'source_remained_outside_scene': True}))
