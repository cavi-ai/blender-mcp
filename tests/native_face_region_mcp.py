"""Pick, grow and finish a source region through MCP, then reopen the saved source."""
import hashlib
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main, verify_source_identity


async def exercise(root,env,parameters=None):
    scoped=parameters is not None
    parameters=parameters or StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(parameters) as streams,ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content

        state=await call('scene_info',limit=1)
        assert Path(state['workspace']).resolve()==root.resolve() and Path(state['file']).resolve()==root/'initial.blend'
        assert state['source_state']['saved_source']['sha256']==hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        before={name:json.loads((root/f'{name}-audit.json').read_text()) for name in ('region','vertex','density')}
        page=await call('scene_info',name='TileGrid',region={'seed':0},limit=1)
        second=await call('scene_info',name='TileGrid',region={'seed':0},limit=1,offset=1)
        assert page['scope']=='source_face_region' and page['total']==second['total']==2
        assert page['region']['selection_sha256']==second['region']['selection_sha256']
        assert [f['index'] for p in (page,second) for f in p['faces']]==[0,1]
        for boundary in ('seam','material'):
            result=await call('scene_info',name='TileGrid',region={'seed':0,'stop_at':[boundary]})
            assert [f['index'] for f in result['faces']]==[0],result
            assert result['region']['selection_sha256']!=page['region']['selection_sha256']
        for name,region,expected in [('FoldedPanel',{'seed':0},[0,1,2]),
                ('FoldedPanel',{'seed':0,'angle_limit_degrees':30},[0]),
                ('FoldedPanel',{'seed':1,'angle_limit_degrees':0},[1,2]),
                ('FoldedPanel',{'seed':0,'angle_limit_degrees':100},[0,1,2]),
                ('FoldedPanel',{'seed':3},[3]),('AmbiguousPanel',{'seed':0},[0])]:
            result=await call('scene_info',name=name,region=region)
            assert [f['index'] for f in result['faces']]==expected,result
        empty=await call('scene_info',name='TileGrid',region={'seed':0},offset=100)
        assert empty['faces']==[] and empty['total']==2
        for change in ({'region':{'seed':20}},{'region':{'seed':True}},{'region':{'seed':0,'stop_at':['seam','seam']}},
                       {'region':{'seed':0,'angle_limit_degrees':181}},{'faces':True}):
            result=await client.call_tool('scene_info',{'name':'TileGrid','region':{'seed':0},**change})
            assert result.is_error,result
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        assert state['source_state']['saved_source']['sha256']==hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='face-region-native',expected_project=owner['project_id']))['lease_id']
        pick=await call('scene_info',name='FoldedPanel',surface_ray={'origin_world':[.5,.5,2],
            'direction_world':[0,0,-1],'max_distance_m':5})
        assert pick['surface_pick']['hit'] and pick['surface_pick']['face_index']==0,pick
        region=await call('scene_info',name='FoldedPanel',region={'seed':pick['surface_pick']['face_index'],
                           'angle_limit_degrees':30})
        await call('asset_io',action='save',path='inspected.blend',lease_id=lease)
        assert {name:json.loads((root/f'{name}-audit.json').read_text()) for name in before}==before
        result=await call('mesh_edit',action='assign_faces',name='FoldedPanel',material_name='TrimFinish',
            face_indices=[f['index'] for f in region['faces']],expected_mesh_sha256=region['mesh_sha256'],lease_id=lease)
        assert result['face_material']['changed_faces']==1 and result['face_material']['face_indices']==[0]
        stale=await client.call_tool('mesh_edit',{'action':'assign_faces','name':'FoldedPanel','material_name':'TrimFinish',
            'face_indices':[0],'expected_mesh_sha256':region['mesh_sha256'],'lease_id':lease})
        assert stale.is_error and stale.structured_content['error']['outcome']=='rejected',stale
        await call('asset_io',action='save',path='finished.blend',lease_id=lease)
        after={name:json.loads((root/f'{name}-audit.json').read_text()) for name in before}
        expected={**before['region']['FoldedPanel'],'slots':[1,0,0,0],
                  'materials':before['region']['FoldedPanel']['materials']+['TrimFinish']}
        assert after['region']['FoldedPanel']==expected
        assert after['region']['AmbiguousPanel']==before['region']['AmbiguousPanel']
        assert all(after[name]==before[name] for name in ('vertex','density'))
        await call('asset_io',action='open',path='finished.blend',lease_id=lease)
        assert (await call('scene_info',name='FoldedPanel',region={'seed':0,'stop_at':['material']}))['total']==1
        await call('asset_io',action='save',path='reopened.blend',lease_id=lease)
        assert {name:json.loads((root/f'{name}-audit.json').read_text()) for name in before}==after
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'source-audits.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
        return {'face_regions':'passed','scoped_profile':scoped,'query_mutations':False,
                'boundaries':['seam','material','angle','nonmanifold','disconnected'],
                'pagination':'stable selection identity','pick_region_assign_reopen':'passed',
                'dedicated_source_identity_test':'passed'}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('face_region_fixture.py'))
