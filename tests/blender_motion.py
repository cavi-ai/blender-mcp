"""Native motion fidelity, driven shapes, export round trips and negative skin test.

Run with Blender --background --factory-startup --python-exit-code 1 --python tests/blender_motion.py.
"""
import sys
import tempfile

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[1] / 'src'))
import math
from pathlib import Path

import bpy

from cavi_blender_mcp import blender_bridge as bridge

for value in list(bpy.data.objects): bpy.data.objects.remove(value,do_unlink=True)
bpy.context.scene.unit_settings.system='METRIC'
bpy.context.scene.unit_settings.scale_length=1
bpy.context.scene.render.fps=24
bpy.context.scene.frame_start=1;bpy.context.scene.frame_end=25
parent=bpy.data.objects.new('BodyControl',None);bpy.context.scene.collection.objects.link(parent)
for frame,x,puff in [(1,0,0),(13,.15,.8),(25,0,0)]:
    parent.location.x=x;parent.keyframe_insert('location',frame=frame)
    parent['puff']=puff;parent.keyframe_insert('["puff"]',frame=frame)
data=bpy.data.armatures.new('LegRig');rig=bpy.data.objects.new('LegRig',data)
bpy.context.scene.collection.objects.link(rig);rig.parent=parent
bpy.context.view_layer.objects.active=rig;rig.select_set(True);bpy.ops.object.mode_set(mode='EDIT')
a=data.edit_bones.new('Thigh');a.head=(0,0,1);a.tail=(0,.05,.55)
b=data.edit_bones.new('Shin');b.head=a.tail;b.tail=(0,0,.05);b.parent=a;b.use_connect=True
bpy.ops.object.mode_set(mode='OBJECT')
goal=bpy.data.objects.new('FootControl',None);bpy.context.scene.collection.objects.link(goal);goal.parent=parent
for frame,y,z in [(1,0,.05),(13,.2,.3),(25,0,.05)]:
    goal.location=(0,y,z);goal.keyframe_insert('location',frame=frame)
pole=bpy.data.objects.new('KneePole',None);bpy.context.scene.collection.objects.link(pole);pole.parent=parent;pole.location=(0,-1,.5)
ik=rig.pose.bones['Shin'].constraints.new('IK');ik.target=goal;ik.pole_target=pole;ik.chain_count=2;ik.use_stretch=False
verts=[];faces=[];segments=16;rings=17
for j in range(rings):
    z=.05+.95*j/(rings-1)
    for i in range(segments):
        angle=2*math.pi*i/segments;radius=.07+.02*math.sin(math.pi*j/(rings-1))
        verts.append((radius*math.cos(angle),radius*math.sin(angle),z))
for j in range(rings-1):
    for i in range(segments):faces.append((j*segments+i,j*segments+(i+1)%segments,(j+1)*segments+(i+1)%segments,(j+1)*segments+i))
mesh=bpy.data.meshes.new('LegSkin');mesh.from_pydata(verts,[],faces);mesh.update()
skin=bpy.data.objects.new('LegSkin',mesh);bpy.context.scene.collection.objects.link(skin);skin.parent=parent
mod=skin.modifiers.new('Skin','ARMATURE');mod.object=rig
for name in ('Thigh','Shin'):skin.vertex_groups.new(name=name)
for v in mesh.vertices:
    upper=max(0,min(1,(v.co.z-.35)/.4))
    for name,weight in [('Thigh',upper),('Shin',1-upper)]:
        if weight:skin.vertex_groups[name].add([v.index],weight,'REPLACE')
skin.shape_key_add(name='Basis');puff=skin.shape_key_add(name='Puff')
for v in puff.data:v.co.x*=1.35;v.co.y*=1.35
driver=puff.driver_add('value').driver;driver.type='SCRIPTED'
var=driver.variables.new();var.name='puff';var.targets[0].id=parent;var.targets[0].data_path='["puff"]';driver.expression='puff'
material=bpy.data.materials.new('LegFinish');material.diffuse_color=(.12,.45,.53,1);skin.data.materials.append(material)
for face in mesh.polygons:face.use_smooth=True
bpy.context.scene.frame_set(7)

with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'motion-test',
                                               'expected_project': state['project_id']})['lease_id']
    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation, 'params': {**params, 'lease_id': lease}})
    original_constraints = len(rig.pose.bones['Shin'].constraints)
    original_driver = skin.data.shape_keys.animation_data.drivers[0].data_path
    result = edit('bake_rig', name='LegRig', new_name='LegFK', action_name='WalkFK',
                  start_frame=1, end_frame=25, frame_step=.1, names=['LegSkin'])
    assert result['shape_keys_baked']
    assert len(rig.pose.bones['Shin'].constraints) == original_constraints
    assert skin.data.shape_keys.animation_data.drivers[0].data_path == original_driver
    baked = bpy.data.objects['LegFK_Skin1']
    assert baked.parent == bpy.data.objects['LegFK']
    assert not baked.data.shape_keys.animation_data.drivers
    params = {'source': 'LegRig', 'candidate': 'LegFK', 'meshes': [{'source': 'LegSkin', 'candidate': baked.name}],
                  'start_frame': 1, 'end_frame': 25, 'max_error_m': .0005, 'samples': 32}
    scene = bpy.context.scene
    scene.frame_set(7, subframe=.375)
    before = (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end)
    compared = bridge.dispatch('compare_rig_motion', params)
    assert compared['passed'], compared
    assert compared['meshes'][0]['source_motion_m'] > .1
    assert before == (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end)
    for extension in ('glb', 'fbx'):
        edit('export_asset', path='motion.'+extension, names=[baked.name], animations=True,
             baked_animation=True, **({'animation_sample_step': .1} if extension == 'fbx' else {}))
        imported = edit('import_mesh' if extension == 'glb' else 'import_fbx', path='motion.'+extension, name='Review_'+extension)
        ids = {item['exported_name']: item['name'] for item in imported['source_objects']
               if item['name'] in imported['armatures'] + imported['skinned_meshes']}
        before = (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end)
        target = bpy.data.objects[ids['LegFK']]
        offset = target.animation_data.action.frame_range[0] - 1
        compared = bridge.dispatch('compare_rig_motion', {**params, 'candidate': target.name,
            'meshes': [{'source': 'LegSkin', 'candidate': ids[baked.name]}],
            'vertex_match': 'point_set', 'candidate_frame_offset': offset})
        assert compared['passed'], compared
        assert before == (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end)
    # A correct bone track must not conceal a corrupted skin assignment.
    for group in baked.vertex_groups:
        group.remove([0])
    baked.vertex_groups['Thigh'].add([0], 1, 'REPLACE')
    compared = bridge.dispatch('compare_rig_motion', params)
    assert not compared['passed'] and compared['max_error_m'] > .001, compared
    assert compared['bone_head_error_m'] < .0005, compared
    assert before == (scene.frame_current, scene.frame_subframe, scene.frame_start, scene.frame_end)
    try:
        edit('bake_rig', name='LegRig', new_name='TooDense', action_name='Dense',
             start_frame=1, end_frame=25, frame_step=1e-320, names=['LegSkin'])
    except ValueError:
        pass
    else:
        raise AssertionError('Unbounded bake sampling accepted')
    assert 'TooDense' not in bpy.data.objects
print('Motion fidelity and both native export round trips passed')
