"""Trim and retime bone, object and driven facial motion without altering the source."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge

with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'clip-test',
        'expected_project': state['project_id']})['lease_id']

    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation,
            'params': {**params, 'lease_id': lease}})

    edit('create_armature', name='Source', bones=[
        {'name': 'Root', 'head': [0, 0, 0], 'tail': [0, 0, 1]},
        {'name': 'Foot', 'head': [0, 0, .1], 'tail': [0, .3, .1], 'parent': 'Root'}])
    bpy.ops.mesh.primitive_cube_add(size=.2, location=(0, 0, .5))
    skin = bpy.context.object
    skin.name = 'Skin'
    edit('bind_skin', name='Source', names=['Skin'])
    for group in skin.vertex_groups:
        group.remove(list(range(len(skin.data.vertices))))
    for vertex in skin.data.vertices:
        bone = 'Root' if vertex.co.z > 0 else 'Foot'
        skin.vertex_groups[bone].add([vertex.index], 1, 'REPLACE')
    skin.shape_key_add(name='Basis')
    shape = skin.shape_key_add(name='Blink')
    for vertex in shape.data:
        vertex.co.z *= .6
    shape.driver_add('value').driver.expression = 'frame/40'
    edit('keyframe_rig', name='Source', action_name='LongTake', keyframes=[
        {'frame': 10, 'poses': [{'bone': 'Root', 'location': [0, 0, 0]},
                              {'bone': 'Foot', 'location': [0, 0, 0]}]},
        {'frame': 30, 'poses': [{'bone': 'Root', 'location': [1, 0, 0]},
                              {'bone': 'Foot', 'location': [-1, 0, 0]}]}])
    source = bpy.data.objects['Source']
    source.rotation_mode = 'XYZ'
    for frame, angle in [(10, 0), (30, .2)]:
        source.rotation_euler.z = angle
        source.keyframe_insert('rotation_euler', frame=frame)
    scene = bpy.context.scene
    scene.frame_set(17, subframe=.375)
    before = (scene.frame_current, scene.frame_subframe, source.animation_data.action,
              len(bpy.data.actions), shape.driver_add('value').driver.expression)
    baked = edit('bake_rig', name='Source', new_name='Clip', action_name='ShortTake',
        names=['Skin'], start_frame=12, end_frame=28, frame_step=.1,
        timing={'start_frame': 2.5, 'playback_rate': 2})
    assert baked['frame_range'] == [2.5, 10.5], baked
    assert baked['source_frame_range'] == [12, 28], baked
    assert baked['frames'][0] == 2.5 and baked['frames'][-1] == 10.5
    params = {'source': 'Source', 'candidate': 'Clip',
        'meshes': [{'source': 'Skin', 'candidate': 'Clip_Skin1'}],
        'start_frame': 12, 'end_frame': 28, 'samples': 32, 'max_error_m': .0005,
        'candidate_frame_scale': .5, 'candidate_frame_offset': -3.5}
    compared = bridge.dispatch('compare_rig_motion', params)
    assert compared['passed'], compared
    assert compared['meshes'][0]['source_motion_m'] > .1, compared
    wrong_time = bridge.dispatch('compare_rig_motion', {**params,
        'candidate_frame_scale': 1, 'candidate_frame_offset': 0})
    assert not wrong_time['passed'], wrong_time
    window = {'bone': 'Foot', 'point': [0, 0, -.1], 'start_frame': 12,
        'end_frame': 28, 'samples': 16, 'max_drift_m': .0005,
        'max_height_error_m': .0005, 'ground_z_m': 0}
    checked = bridge.dispatch('inspect_rig', {'armature': 'Clip', 'meshes': ['Clip_Skin1'],
        'action': 'ShortTake', 'contacts': [window], 'contact_frame_scale': .5,
        'contact_frame_offset': -3.5,
        'contact_reference': {'armature': 'Source', 'action': 'LongTake'}})
    contact = checked['animation_checks']['contacts'][0]
    assert contact['passed'], contact
    assert contact['sample_frames'][0] == 2.5 and contact['sample_frames'][-1] == 10.5
    assert contact['reference_sample_frames'][0] == 12 and contact['reference_sample_frames'][-1] == 28
    exported = edit('export_asset', path='fractional.fbx', names=['Clip_Skin1'],
        animations=True, baked_animation=True, animation_sample_step=.05)
    assert exported['animation_frame_range'] == [2, 11], exported
    imported = edit('import_fbx', path='fractional.fbx', name='Imported')
    mapping = {item['exported_name']: item['name'] for item in imported['source_objects']
               if item['name'] in imported['armatures']+imported['skinned_meshes']}
    imported_rig = bpy.data.objects[mapping['Clip']]
    first, last = imported_rig.animation_data.action.frame_range
    assert abs(last-first-9) < 1e-4, (first, last)
    delivered = bridge.dispatch('compare_rig_motion', {**params, 'candidate': mapping['Clip'],
        'meshes': [{'source': 'Skin', 'candidate': mapping['Clip_Skin1']}],
        'vertex_match': 'point_set', 'candidate_frame_offset': -3.5+first-2})
    assert delivered['passed'], delivered
    assert (scene.frame_current, scene.frame_subframe, source.animation_data.action) == before[:3]
    assert shape.driver_add('value').driver.expression == before[4]
    for rate in (0, 1e300):
        try:
            edit('bake_rig', name='Source', new_name='Invalid', action_name='InvalidTake',
                names=['Skin'], start_frame=12, end_frame=28,
                timing={'start_frame': 1, 'playback_rate': rate})
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid or indistinguishable sample times accepted')
        assert 'Invalid' not in bpy.data.objects and 'InvalidTake' not in bpy.data.actions
    print(json.dumps({'max_error_m': compared['max_error_m'],
        'wrong_time_error_m': wrong_time['max_error_m'], 'contact': contact['passed'],
        'output_range': baked['frame_range'], 'source_preserved': True,
        'fbx_error_m': delivered['max_error_m']}))
