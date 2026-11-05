"""Run normal object handlers alongside the source-UV dispatch branch."""
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cavi_blender_mcp import blender_bridge as bridge

before=bridge.dispatch('scene_info',{'limit':1})
state=bridge.dispatch('session_control',{'action':'inspect'})
lease=bridge.dispatch('session_control',{'action':'claim','owner':'dispatch-check',
    'expected_project':state['project_id']})['lease_id']
def edit(operation, **params):
    return bridge.dispatch('owned_edit',{'operation':operation,'params':{**params,'lease_id':lease}})
result=edit('transform_object',name='Cube',location=[1,2,3])
assert result['location']==[1,2,3] and tuple(bpy.data.objects['Cube'].location)==(1,2,3)
created=edit('create_primitive',name='DispatchProbe',kind='cube',location=[0,0,0])
assert created['name']=='DispatchProbe' and created['type']=='MESH'
after=bridge.dispatch('scene_info',{'limit':1})
assert after['total']==before['total']+1
bridge.dispatch('session_control',{'action':'release','lease_id':lease})
print(json.dumps({'native_object_dispatch':'passed','scene_info':True,'object_transform':True,'object_creation':True}))
