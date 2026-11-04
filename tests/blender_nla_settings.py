"""Native layered animation, sparse edits, rollback, bake and saved-source checks."""

import json
import math
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

with tempfile.TemporaryDirectory() as folder:
    root = Path(folder)
    bridge._workspace = root
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'nla-settings-fixture',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})

    edit('create_armature', name='Performance', bones=[
        {'name': 'Root', 'head': [0, 0, -1], 'tail': [0, 0, 0]},
        {'name': 'Spine', 'head': [0, 0, 0], 'tail': [0, 0, 1], 'parent': 'Root'}])
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8)
    bpy.context.object.name = 'Skin'
    edit('bind_skin', name='Performance', names=['Skin'])
    for action, bone, angles in [('Idle', 'Root', [0, 0, 0]), ('Gesture', 'Spine', [0, 45, 0])]:
        edit('keyframe_rig', name='Performance', action_name=action, keyframes=[
            {'frame': frame, 'poses': [{'bone': bone, 'rotation_degrees': [0, 0, angle]}]}
            for frame, angle in zip([1, 11, 21], angles, strict=True)])
    edit('nla_push', name='Performance', action_name='Idle', track_name='Base', strip_name='Idle',
        strip_settings={'repeat': 2, 'extrapolation': 'NOTHING'})
    pushed = edit('nla_push', name='Performance', action_name='Gesture', track_name='Gesture', strip_name='Wave',
        strip_settings={'repeat': 2, 'blend_in': 5, 'blend_out': 5, 'blend_type': 'COMBINE', 'extrapolation': 'NOTHING'})
    assert pushed['frame_range'] == [1, 41], pushed
    changed = edit('nla_edit', name='Performance', track_name='Gesture', strip_name='Wave',
        strip_settings={'frame_start': 5.5, 'action_frame_start': 3, 'action_frame_end': 19,
                        'scale': .5, 'blend_in': 1, 'blend_out': 2})
    assert changed['frame_range'] == [5.5, 21.5], changed
    assert changed['strip_settings']['repeat'] == 2 and changed['strip_settings']['blend_type'] == 'COMBINE'
    shortened = edit('nla_edit', name='Performance', track_name='Gesture', strip_name='Wave',
        strip_settings={'action_frame_start': 3, 'action_frame_end': 6, 'scale': 1,
                        'repeat': 1, 'blend_in': 1, 'blend_out': 1})
    assert shortened['frame_range'] == [5.5, 8.5], shortened
    edit('nla_edit', name='Performance', track_name='Gesture', strip_name='Wave',
        strip_settings={'frame_start': 1, 'action_frame_start': 1, 'action_frame_end': 21,
                        'scale': 1, 'repeat': 2, 'blend_in': 5, 'blend_out': 5})
    rig = bpy.data.objects['Performance']
    wave = rig.animation_data.nla_tracks['Gesture'].strips['Wave']
    before = (wave.frame_start, wave.frame_end, wave.action_frame_start, wave.action_frame_end, wave.scale)
    edit('nla_push', name='Performance', action_name='Gesture', track_name='Gesture', strip_name='Later', start_frame=50)
    try:
        edit('nla_edit', name='Performance', track_name='Gesture', strip_name='Wave',
            strip_settings={'frame_start': 40})
    except ValueError as error:
        assert 'overlap' in str(error), error
    else:
        raise AssertionError('Overlapping same-track strips were accepted')
    assert before == (wave.frame_start, wave.frame_end, wave.action_frame_start, wave.action_frame_end, wave.scale)
    edit('nla_remove', name='Performance', track_name='Gesture', strip_name='Later')
    try:
        edit('nla_edit', name='Performance', track_name='Gesture', strip_name='Wave',
            strip_settings={'frame_start': 1e12})
    except (ValueError, RuntimeError):
        pass
    else:
        raise AssertionError('Native frame clamping was silently accepted')
    assert before == (wave.frame_start, wave.frame_end, wave.action_frame_start, wave.action_frame_end, wave.scale)
    angles = []
    for frame in [1, 4, 11, 21, 31, 41]:
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        angles.append(math.degrees(rig.pose.bones['Spine'].matrix_basis.to_euler().z))
    assert abs(angles[2]-45) < .001 and abs(angles[4]-45) < .001, angles
    assert 0 < angles[1] < 45 and abs(angles[-1]) < .001, angles
    edit('bake_rig', name='Performance', names=['Skin'], new_name='Performance_Baked',
        action_name='LayeredPerformance', start_frame=1, end_frame=41, frame_step=.1)
    comparison = bridge.dispatch('compare_rig_motion', {'source': 'Performance', 'candidate': 'Performance_Baked',
        'meshes': [{'source': 'Skin', 'candidate': 'Performance_Baked_Skin1'}],
        'start_frame': 1, 'end_frame': 41, 'samples': 32, 'max_error_m': .0005,
        'space': 'world', 'vertex_match': 'index'})
    assert comparison['passed'], comparison
    edit('export_asset', names=['Performance_Baked_Skin1'], path='performance.glb', animations=True)
    edit('export_asset', names=['Performance_Baked_Skin1'], path='performance.fbx', animations=True, baked_animation=True)
    save = root/'performance.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(save))
    bpy.ops.wm.open_mainfile(filepath=str(save))
    wave = bpy.data.objects['Performance'].animation_data.nla_tracks['Gesture'].strips['Wave']
    assert wave.repeat == 2 and wave.blend_type == 'COMBINE' and wave.blend_in == wave.blend_out == 5
    assert bpy.data.actions['Gesture'].frame_range[:] == (1, 21)
    print(json.dumps({'layered_pose_angles': angles, 'bake_max_error_m': comparison['max_error_m'],
                      'source_reopened': True, 'native_clamp_rollback': True}))
