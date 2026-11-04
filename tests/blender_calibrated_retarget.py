"""Native calibrated rotation, proportions, root displacement and contact measurements."""
import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge

folder=tempfile.TemporaryDirectory();bridge._workspace=Path(folder.name)
state=bridge.dispatch('session_control',{'action':'inspect'})
lease=bridge.dispatch('session_control',{'action':'claim','owner':'calibration-test','expected_project':state['project_id']})['lease_id']
def edit(operation,**params):return bridge.dispatch('owned_edit',{'operation':operation,'params':{**params,'lease_id':lease}})
for name,height,arm in [('Source',1,(1,0,1)),('Target',1.6,(1,0,2))]:
    edit('create_armature',name=name,bones=[{'name':'Root','head':[0,0,0],'tail':[0,0,.3]},
        {'name':'Leg','parent':'Root','head':[0,0,height],'tail':[0,0,.2]},
        {'name':'Foot','parent':'Leg','head':[0,0,.2],'tail':[0,-.3,.2]},
        {'name':'Arm','parent':'Root','head':[0,0,height],'tail':list(arm),'roll_degrees':37 if name=='Target' else 0}])
source=bpy.data.objects['Source'];target=bpy.data.objects['Target']
bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8);skin=bpy.context.object;skin.name='TargetSkin'
edit('bind_skin',name='Target',names=[skin.name])
edit('keyframe_rig',name='Source',action_name='Motion',keyframes=[
 {'frame':1,'poses':[{'bone':'Root','location':[0,0,0]},{'bone':'Arm','rotation_degrees':[0,0,0]}]},
 {'frame':11,'poses':[{'bone':'Root','location':[2,0,0]},{'bone':'Arm','rotation_degrees':[45,0,0]}]}])
scene=bpy.context.scene;scene.frame_set(7,subframe=.25)
previous=(scene.frame_current,scene.frame_subframe)
result=edit('retarget_rig',name='Target',source='Source',source_action='Motion',action_name='Calibrated',calibration={'root':'Root','root_translation_scale':1.5,'alignment_degrees':[0,0,0]})
assert (scene.frame_current,scene.frame_subframe)==previous
scene.frame_set(1);bpy.context.view_layer.update()
for bone in target.pose.bones:
    assert (bone.matrix.translation-bone.bone.head_local).length<1e-5,(bone.name,bone.matrix.translation,bone.bone.head_local)
    assert bone.matrix.to_quaternion().rotation_difference(bone.bone.matrix_local.to_quaternion()).angle<1e-4,bone.name
scene.frame_set(11);bpy.context.view_layer.update()
assert abs(target.pose.bones['Root'].head.x-3)<1e-5
source_rotation=source.pose.bones['Arm'].matrix.to_quaternion()
rest=source.data.bones['Arm'].matrix_local.to_quaternion()
expected=source_rotation @ rest.inverted() @ target.data.bones['Arm'].matrix_local.to_quaternion()
assert target.pose.bones['Arm'].matrix.to_quaternion().rotation_difference(expected).angle<1e-4
for bone in target.pose.bones:
    assert abs((bone.tail-bone.head).length-bone.bone.length)<1e-5,bone.name
contact={'bone':'Foot','point':[0,0,0],'start_frame':1,'end_frame':11,'samples':9,'max_drift_m':3.1,'max_height_error_m':1e-5,'ground_z_m':.2}
def inspect_contact(profile):return bridge.dispatch('inspect_rig',{'armature':'Target','meshes':['TargetSkin'],'action':'Calibrated','contacts':[profile]})['animation_checks']['contacts'][0]
scene.frame_set(6,subframe=.5);previous=(scene.frame_current,scene.frame_subframe);old_action=target.animation_data.action
report=inspect_contact(contact)
assert report['passed'] and abs(report['max_drift_m']-3)<1e-5,report
assert (scene.frame_current,scene.frame_subframe)==previous and target.animation_data.action==old_action
negative=inspect_contact({**contact,'max_drift_m':.01});assert not negative['passed'],negative
negative_height=inspect_contact({**contact,'ground_z_m':.3});assert not negative_height['passed'],negative_height
before=set(bpy.data.actions)
try:edit('retarget_rig',name='Target',source='Source',source_action='Motion',action_name='BadRoot',calibration={'root':'Leg','root_translation_scale':1,'alignment_degrees':[0,0,0]})
except ValueError:pass
else:raise AssertionError('Nonroot translation driver accepted')
assert set(bpy.data.actions)==before
# A saved source with no active action must keep its current unkeyed pose.
source.animation_data.action = None
source.pose.bones['Root'].location = (.7, .1, .2)
source.pose.bones['Arm'].rotation_mode = 'XYZ'
source.pose.bones['Arm'].rotation_euler = (.1, .2, .3)
from cavi_blender_mcp.blender_animation import snapshot

saved_pose = snapshot(source)
edit('retarget_rig', name='Target', source='Source', source_action='Motion',
     action_name='Aligned', calibration={'root': 'Root', 'root_translation_scale': 1,
                                         'alignment_degrees': [0, 0, 90]})
assert source.animation_data.action is None
assert snapshot(source) == saved_pose
scene.frame_set(11);bpy.context.view_layer.update()
assert abs(target.pose.bones['Root'].head.y - 2) < 1e-5
assert abs(target.pose.bones['Root'].head.x) < 1e-5
print(json.dumps({'calibration':result.get('calibration'),'contacts':report,'negative_contact_passed':negative['passed']}))
folder.cleanup()
