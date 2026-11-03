"""Native IK/pole, rotation limits, exact weights and constraint-free export copies."""

import json
import struct
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge

with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'rig-controls-test',
                                              'expected_project': state['project_id']})['lease_id']
    def edit(operation, **params):
        return bridge.dispatch('owned_edit', {'operation': operation,
                               'params': {**params, 'lease_id': lease}})

    edit('create_armature', name='Leg', bones=[
        {'name':'Root','head':[0,0,0],'tail':[0,0,1]},
        {'name':'Thigh','head':[0,0,1],'tail':[0,0,2],'parent':'Root','connect':True},
        {'name':'Shin','head':[0,0,2],'tail':[.2,0,3],'parent':'Thigh','connect':True},
        {'name':'FootControl','head':[.5,0,2.5],'tail':[.5,0,2.9],'deform':False},
        {'name':'Pole','head':[0,-1,1.8],'tail':[0,-1,2.2],'deform':False}])
    rig = bpy.data.objects['Leg']
    edit('add_constraint', name='Leg', constraint={'type':'IK','name':'Foot IK','bone':'Shin',
         'target':'Leg','subtarget':'FootControl','pole_target':'Leg','pole_subtarget':'Pole',
         'chain_count':2,'pole_angle_degrees':90,'use_stretch':False})
    edit('add_constraint', name='Leg', constraint={'type':'LIMIT_ROTATION',
         'name':'Root limit','bone':'Root','minimum_degrees':[-10,-20,-30],
         'maximum_degrees':[10,20,30],'axes':[True,True,True]})
    assert rig.pose.bones['Shin'].constraints['Foot IK'].pole_subtarget == 'Pole'
    assert abs(rig.pose.bones['Root'].constraints['Root limit'].max_z-.5235988)<1e-6
    mesh_data=bpy.data.meshes.new('Skin')
    mesh_data.from_pydata([(0,0,1),(0,0,2),(.2,0,3),(.2,.2,1.5),(-.2,0,1.5)],[],
                          [(0,1,3),(1,2,3),(0,3,4)])
    skin=bpy.data.objects.new('Skin',mesh_data);bpy.context.scene.collection.objects.link(skin)
    modifier=skin.modifiers.new('Armature','ARMATURE');modifier.object=rig
    mask=skin.vertex_groups.new(name='FinishMask');mask.add(list(range(5)),.345678,'REPLACE')
    root=skin.vertex_groups.new(name='Root');root.add([4],1,'REPLACE')
    edit('assign_weights',name='Skin',vertex_weights=[
        {'vertex':0,'weights':{'Root':1}}, {'vertex':1,'weights':{'Thigh':.75,'Shin':.25}},
        {'vertex':2,'weights':{'Shin':1}},
        {'vertex':3,'weights':{'Root':.234567,'Thigh':.765433}}])
    assert abs(skin.vertex_groups['Root'].weight(3)-.234567)<1e-7
    assert abs(mask.weight(3)-.345678)<1e-7 and root.weight(4)==1
    before=[[(g.group,g.weight) for g in v.groups] for v in skin.data.vertices]
    for invalid in ([{'vertex':1,'weights':{'NotABone':1}}],
                    [{'vertex':100,'weights':{'Root':1}}],
                    [{'vertex':1,'weights':{'Root':.5}},{'vertex':1,'weights':{'Root':.5}}]):
        try:edit('assign_weights',name='Skin',vertex_weights=invalid)
        except ValueError:pass
        else:raise AssertionError('Invalid weights accepted')
        assert before==[[(g.group,g.weight) for g in v.groups] for v in skin.data.vertices]
    edit('keyframe_rig',name='Leg',action_name='Walk',keyframes=[
        {'frame':1,'poses':[{'bone':'FootControl','location':[0,0,0]}]},
        {'frame':12,'poses':[{'bone':'FootControl','location':[.3,.1,-.3]}]},
        {'frame':24,'poses':[{'bone':'FootControl','location':[0,0,0]}]}])
    scene=bpy.context.scene;scene.frame_set(5);original_action=rig.animation_data.action
    for frame, x in ((1,0), (12,.15), (24,0)):
        skin.location.x = x
        skin.keyframe_insert('location', frame=frame)
    result=edit('bake_rig',name='Leg',new_name='Leg_Baked',action_name='Walk_Baked',
                start_frame=1,end_frame=24,frame_step=1,names=['Skin'])
    baked=bpy.data.objects['Leg_Baked'];baked_skin=bpy.data.objects['Leg_Baked_Skin1']
    assert scene.frame_current==5 and rig.animation_data.action==original_action
    assert rig.pose.bones['Shin'].constraints.get('Foot IK') is not None
    assert all(not b.constraints for b in baked.pose.bones)
    assert next(m for m in baked_skin.modifiers if m.type=='ARMATURE').object==baked
    assert baked_skin.animation_data.action == baked.animation_data.action
    maximum=0
    for frame in (1,5,12,18,24):
        scene.frame_set(frame);deps=bpy.context.evaluated_depsgraph_get()
        evaluated=rig.evaluated_get(deps)
        distance=(evaluated.pose.bones['Shin'].tail-
                  evaluated.pose.bones['FootControl'].head).length
        assert distance<.002,distance
        left,right=skin.evaluated_get(deps),baked_skin.evaluated_get(deps)
        lm,rm=left.to_mesh(),right.to_mesh()
        try:
            error=max(((left.matrix_world@a.co)-(right.matrix_world@b.co)).length
                      for a,b in zip(lm.vertices,rm.vertices,strict=True))
            maximum=max(maximum,error)
        finally:left.to_mesh_clear();right.to_mesh_clear()
    assert maximum<1e-4,maximum
    edit('export_asset', path='baked.glb', names=['Leg_Baked_Skin1'], animations=True)
    glb=(Path(folder)/'baked.glb').read_bytes()
    length=struct.unpack_from('<I',glb,12)[0]
    document=json.loads(glb[20:20+length])
    clips=[a['name'] for a in document['animations']]
    assert clips==['Walk_Baked'],clips
    save=Path(folder)/'rig.blend';bpy.ops.wm.save_as_mainfile(filepath=str(save))
    bpy.ops.wm.open_mainfile(filepath=str(save))
    assert bpy.data.objects['Leg_Baked'].animation_data.action.name=='Walk_Baked'
    assert bpy.data.objects['Leg'].pose.bones['Shin'].constraints['Foot IK'].pole_subtarget=='Pole'
    print(json.dumps({'samples':len(result['frames']), 'matrix_error':result[
        'maximum_matrix_component_error'],'skin_error_metres':maximum,
        'source_constraints_preserved':True,'editable_blend_reopened':True}))
