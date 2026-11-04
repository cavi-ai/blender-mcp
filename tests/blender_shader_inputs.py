"""Native shader edits preserve topology, context, rollback and saved defaults."""

import json
import os
import runpy
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_shader_inputs as shader
from cavi_blender_mcp.blender_asset_library import ids
from cavi_blender_mcp.blender_materials import CONFIG_TAG

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    os.environ['CAVI_BLENDER_WORKSPACE'] = str(root)
    runpy.run_path(str(Path(__file__).with_name('shader_input_fixture.py')))
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'baseline.blend'))
    context = bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    before_ids = ids()
    args = {'material_name': 'ArtistFinish', 'group_path': ['Finish Controls', 'Inner Layer'], 'node': 'Hero Surface'}
    original = bridge.dispatch('inspect_material_nodes', args)
    assert not bpy.data.is_dirty and ids() == before_ids
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'shader-context',
        'expected_project': state['project_id']})['lease_id']

    def edit(**updates):
        return bridge.dispatch('owned_edit', {'operation': 'set_material_inputs',
            'params': {**args, 'lease_id': lease, **updates}})

    configs = {name: bpy.data.materials[name][CONFIG_TAG] for name in ['ManagedA', 'ManagedB']}
    # An existing provenance value must also survive a post-mutation failure.
    bpy.data.materials['ManagedA'][shader.PROVENANCE_TAG] = 'earlier source'
    with patch.object(shader, 'node_report', side_effect=RuntimeError('receipt failed')):
        try:
            edit(inputs={'Coat Weight': .4})
        except RuntimeError as exc:
            assert str(exc) == 'receipt failed'
        else:
            raise AssertionError('Injected receipt failure succeeded')
    assert bridge.dispatch('inspect_material_nodes', args) == original
    assert all(bpy.data.materials[name][CONFIG_TAG] == config for name, config in configs.items())
    assert bpy.data.materials['ManagedA'][shader.PROVENANCE_TAG] == 'earlier source'
    assert shader.PROVENANCE_TAG not in bpy.data.materials['ManagedB']
    noop = edit(inputs={'Coat Weight': 0.})
    assert noop['changed_inputs'] == [] and noop['managed_materials_detached'] == []
    result = edit(inputs={'Coat Weight': .4, 'Roughness': .33})
    assert result['links'] == original['links'] and ids() == before_ids
    assert result['managed_materials_detached'] == ['ManagedA', 'ManagedB']
    assert context == (bpy.data.filepath, bpy.context.scene, set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    for name, config in configs.items():
        material = bpy.data.materials[name]
        assert CONFIG_TAG not in material and material[shader.PROVENANCE_TAG] == config
        assert material['artist_note'] == 'retain'
    bpy.ops.wm.save_as_mainfile(filepath=str(root/'authored.blend'))
    bpy.ops.wm.open_mainfile(filepath=str(root/'authored.blend'))
    saved = shader.inspect({**args, 'limit': 1})
    assert saved == {k: v for k, v in result.items() if k not in {'changed_inputs', 'managed_materials_detached'}}
    for name, config in configs.items():
        assert bpy.data.materials[name][shader.PROVENANCE_TAG] == config
    assert bpy.data.materials['ArtistFinish'].node_tree.nodes['Finish Controls'].node_tree == bpy.data.materials['OtherFinish'].node_tree.nodes['Finish Controls'].node_tree
    print(json.dumps({'native_shader_inputs': 'passed', 'rollback_defaults_and_tags': True,
        'inspection_no_ids_or_dirty_file': True, 'context_and_topology_preserved': True,
        'noop_keeps_managed_configuration': True, 'save_reopen': True}))
