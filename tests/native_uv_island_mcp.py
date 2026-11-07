"""Select and move one texture island through the real leased MCP surface."""
import copy
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
        saved=hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        assert state['source_state']['saved_source']['sha256']==saved
        before=json.loads((root/'vertex-audit.json').read_text())
        layer_before=json.loads((root/'density-audit.json').read_text())

        async def region(layer=None,stops=None,**page):
            args={} if layer is None else {'uv_layer':layer}
            return await call('scene_info',name='TileGrid',region={'seed':0,'stop_at':stops or []},**args,**page)

        assert (await region())['total']==2
        island=await region('UVMap',['uv'])
        assert [f['index'] for f in island['faces']]==[0],island
        assert island['uv']['layer']=='UVMap'
        continuous=await region('Continuous',['uv'],limit=1)
        second=await region('Continuous',['uv'],limit=1,offset=1)
        assert continuous['total']==second['total']==2
        assert continuous['region']==second['region'] and continuous['uv']==second['uv']
        assert [f['index'] for p in (continuous,second) for f in p['faces']]==[0,1]
        assert (await region('NearContinuous',['uv']))['total']==1
        assert (await region('Continuous',['uv','material']))['total']==1
        for args in ({'region':{'seed':0,'stop_at':['uv']}},
                     {'region':{'seed':0,'stop_at':['uv']},'uv_layer':'missing'},
                     {'region':{'seed':0},'uv_layer':'Continuous'}):
            result=await client.call_tool('scene_info',{'name':'TileGrid',**args})
            assert result.is_error,result
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='uv-island-native',expected_project=owner['project_id']))['lease_id']
        await call('asset_io',action='save',path='inspected.blend',lease_id=lease)
        assert json.loads((root/'vertex-audit.json').read_text())==before
        assert json.loads((root/'density-audit.json').read_text())==layer_before
        args={'action':'uv_transform','name':'TileGrid','uv_layer':'UVMap',
              'uv_transform':{'faces':[f['index'] for f in island['faces']],'offset':[.125,0]},
              'expected_mesh_sha256':island['mesh_sha256'],'expected_uv_sha256':island['uv']['sha256'],'lease_id':lease}
        changed=await call('mesh_edit',**args)
        current=await region('UVMap',['uv'])
        assert current['mesh_sha256']==island['mesh_sha256']
        assert current['faces']==island['faces'] and current['uv']!=island['uv']
        assert current['region']['selection_sha256']!=island['region']['selection_sha256']
        assert changed['uv_transform']['uv_sha256_before']==island['uv']['sha256']
        assert changed['uv_transform']['uv_sha256_after']==current['uv']['sha256']
        rejected=await client.call_tool('mesh_edit',args)
        assert rejected.is_error and rejected.structured_content['error']['outcome']=='rejected',rejected
        await call('asset_io',action='save',path='finished.blend',lease_id=lease)
        after=json.loads((root/'vertex-audit.json').read_text())
        expected=copy.deepcopy(before)
        # The fixture's first polygon owns loops 0..3. All other UVs and rig data stay exact.
        for uv in expected['objects']['TileGrid']['uvs']['UVMap'][:4]:
            uv[0]+=.125
        assert after==expected,(after,expected)
        layer_expected=copy.deepcopy(layer_before)
        layer_expected['uvs']=expected['objects']['TileGrid']['uvs']
        assert json.loads((root/'density-audit.json').read_text())==layer_expected
        await call('asset_io',action='open',path='finished.blend',lease_id=lease)
        reopened=await region('UVMap',['uv'])
        assert reopened['uv']==current['uv'] and reopened['region']==current['region']
        await call('asset_io',action='save',path='reopened.blend',lease_id=lease)
        assert json.loads((root/'vertex-audit.json').read_text())==after
        assert json.loads((root/'density-audit.json').read_text())==layer_expected
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'source-audits.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
        return {'uv_islands':'passed','scoped_profile':scoped,'exact_float32_boundary':'passed',
                'pagination':'stable','stale_uv_rejected':'passed','neighbor_uvs_and_rig_data':'unchanged',
                'save_reopen':'passed','dedicated_source_identity_test':'passed'}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('uv_island_fixture.py'))
