"""Native facial layers, slot ownership and independent evaluated motion bake."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'facial-nla-fixture',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    def refused(operation, message, **params):
        try:
            edit(operation, **params)
        except (ValueError, RuntimeError) as exc:
            assert message in str(exc), exc
        else:
            raise AssertionError(f'{operation} accepted {params}')

    edit('create_armature', name='Rig', bones=[{'name': 'Head', 'head': [0, 0, 0], 'tail': [0, 0, 1]}])
    edit('keyframe_rig', name='Rig', action_name='Body', keyframes=[
        {'frame': f, 'poses': [{'bone': 'Head', 'rotation_degrees': [0, 0, a]}]}
        for f, a in [(1, 0), (6, 20), (11, 0)]])
    edit('nla_push', name='Rig', action_name='Body', track_name='Body', strip_name='Body')
    bpy.ops.mesh.primitive_cube_add()
    skin = bpy.context.object
    skin.name = 'Face'
    edit('bind_skin', name='Rig', names=['Face'])
    for name, index, delta in [('Blink', 0, [0, 0, -.2]), ('Smile', 1, [.1, 0, 0])]:
        edit('shape_key_add', name='Face', new_name=name, offsets=[[index, *delta]])
        edit('shape_key_keyframe', name='Face', new_name=name, action_name=name, keyframes=[
            {'frame': f, 'value': v} for f, v in [(1, 0), (6, 1), (11, 0)]])
        pushed = edit('nla_push', name='Face', animation_target='SHAPE_KEYS', action_name=name,
            track_name=name, strip_name=name, strip_settings={'repeat': 2, 'extrapolation': 'NOTHING'})
        assert pushed['animation_target'] == 'SHAPE_KEYS', pushed
        assert pushed['name'] == 'Face' and pushed['active_action'] is None, pushed
    keys = skin.data.shape_keys
    assert keys.animation_data.action is None and skin.animation_data is None
    assert len(bpy.data.objects['Rig'].animation_data.nla_tracks) == 1
    bpy.context.scene.frame_set(6)
    assert abs(keys.key_blocks['Blink'].value - 1) < 1e-6
    assert abs(keys.key_blocks['Smile'].value - 1) < 1e-6
    before = [(s.name, s.action.name, s.action_slot.identifier) for t in keys.animation_data.nla_tracks for s in t.strips]
    refused('set_action', 'KEY', name='Face', animation_target='SHAPE_KEYS', action_name='Body')
    refused('nla_push', 'KEY', name='Face', animation_target='SHAPE_KEYS', action_name='Body')
    refused('set_action', 'OBJECT', name='Rig', action_name='Blink')
    assert keys.animation_data.action is None
    assert before == [(s.name, s.action.name, s.action_slot.identifier) for t in keys.animation_data.nla_tracks for s in t.strips]
    assigned = edit('set_action', name='Face', animation_target='SHAPE_KEYS', action_name='Blink')
    assert assigned['active_action'] == 'Blink'
    refused('set_action', 'KEY', name='Face', animation_target='SHAPE_KEYS', action_name='Body')
    assert keys.animation_data.action.name == 'Blink'
    edit('set_action', name='Face', animation_target='SHAPE_KEYS')
    changed = edit('nla_edit', name='Face', animation_target='SHAPE_KEYS', track_name='Smile', strip_name='Smile',
        strip_settings={'frame_start': 3.5, 'scale': .5, 'influence': .5, 'use_animated_influence': True, 'blend_type': 'ADD'})
    assert changed['frame_range'] == [3.5, 13.5], changed
    bpy.context.scene.frame_set(6)
    assert abs(keys.key_blocks['Smile'].value - .5) < 1e-6, keys.key_blocks['Smile'].value
    inspected = bridge.dispatch('inspect_rig', {'armature': 'Rig', 'meshes': ['Face']})
    face = inspected['meshes'][0]['shape_key_animation']
    assert next(a for a in inspected['actions'] if a['name'] == 'Blink')['target_types'] == ['KEY']
    assert face['active_action'] is None and len(face['nla_tracks']) == 2, face
    assert all(s['action_slot'].startswith('KE') for t in face['nla_tracks'] for s in t['strips']), face
    # A datablock with several compatible slots needs an exact owner match.
    ambiguous = bpy.data.actions.new('Ambiguous')
    ambiguous.slots.new('KEY', 'OtherA')
    ambiguous.slots.new('KEY', 'OtherB')
    refused('set_action', 'ambiguous', name='Face', animation_target='SHAPE_KEYS', action_name='Ambiguous')
    assert keys.animation_data.action is None
    selected = ambiguous.slots.new('KEY', keys.name)
    edit('set_action', name='Face', animation_target='SHAPE_KEYS', action_name='Ambiguous')
    assert keys.animation_data.action_slot == selected
    edit('set_action', name='Face', animation_target='SHAPE_KEYS')
    # Shared meshes must not silently change a second character's performance.
    linked = bpy.data.objects.new('LinkedFace', skin.data)
    bpy.context.collection.objects.link(linked)
    refused('nla_remove', 'single-user', name='Face', animation_target='SHAPE_KEYS')
    bpy.data.objects.remove(linked, do_unlink=True)
    refused('nla_edit', 'animation_target', name='Rig', animation_target='invented')
    edit('bake_rig', name='Rig', names=['Face'], new_name='Baked', action_name='Performance',
        start_frame=1, end_frame=21, frame_step=.1)
    copied = bpy.data.objects['Baked_Skin1'].data.shape_keys
    assert not copied.animation_data.nla_tracks
    assert copied != keys and copied.animation_data.action != keys.animation_data.action
    compared = bridge.dispatch('compare_rig_motion', {'source': 'Rig', 'candidate': 'Baked',
        'meshes': [{'source': 'Face', 'candidate': 'Baked_Skin1'}], 'start_frame': 1, 'end_frame': 21,
        'samples': 32, 'max_error_m': .0005, 'space': 'world', 'vertex_match': 'index'})
    assert compared['passed'], compared
    source = Path(folder) / 'layered.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(source))
    bpy.ops.wm.open_mainfile(filepath=str(source))
    saved = bpy.data.objects['Face'].data.shape_keys.animation_data
    assert len(saved.nla_tracks) == 2 and saved.action is None
    bridge.dispatch('session_control', {'action': 'release', 'lease_id': lease})
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'facial-nla-fixture',
        'expected_project': state['project_id']})['lease_id']
    edit('nla_remove', name='Face', animation_target='SHAPE_KEYS', track_name='Smile')
    assert len(saved.nla_tracks) == 1
    assert len(bpy.data.objects['Rig'].animation_data.nla_tracks) == 1
    print(json.dumps({'blender': bpy.app.version_string, 'bake_max_error_m': compared['max_error_m'],
                      'saved_layers': 2, 'slot_and_owner_rejections': True}))
