"""One read-only source/posed surface-pick case through the actual scoped MCP."""
import hashlib
import json
import math
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root,env,parameters=None):
    parameters=parameters or StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(parameters) as streams,ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content

        target=await call('scene_info',limit=1)
        assert Path(target['workspace']).resolve()==root.resolve()
        assert Path(target['file']).resolve()==root/'initial.blend'
        assert target['source_state']['saved_source']['sha256']==hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        before=json.loads((root/'pick-audit.json').read_text())
        references=json.loads((root/'pick-reference.json').read_text())
        receipts={}
        for mode,reference in references.items():
            result=await call('scene_info',name='PickTarget',surface_ray=reference['ray'],uv_layer='SourceUV')
            hit=result['surface_pick']
            assert result['scope']=='mesh_surface_pick' and hit['hit'] and hit['face_index']==0,hit
            assert set(hit['triangle_vertices'])=={0,1,2} and hit['material_index']==0,hit
            assert math.isclose(hit['distance_m'],.02,abs_tol=2e-7),hit
            for field in ('position_local','position_world','normal_world'):
                assert all(math.isclose(a,b,abs_tol=2e-6) for a,b in zip(hit[field],reference[field],strict=True)),hit
            assert all(math.isclose(a,b,abs_tol=2e-6) for a,b in zip(hit['uv']['position'],[.34,.5],strict=True)),hit
            assert math.isclose(sum(hit['barycentric']),1.,abs_tol=1e-7)
            assert hit['frame']==3 and hit['frame_subframe']==.25
            receipts[mode]=result
        assert math.dist(receipts['source']['surface_pick']['position_world'],receipts['evaluated']['surface_pick']['position_world'])>.01
        assert receipts['source']['mesh_sha256']==receipts['evaluated']['mesh_sha256']
        assert receipts['source']['surface_pick']['surface_sha256']!=receipts['evaluated']['surface_pick']['surface_sha256']
        ray=references['evaluated']['ray']
        for change in ({'max_distance_m':.005},{'direction_world':[-v for v in ray['direction_world']]}):
            miss=await call('scene_info',name='PickTarget',surface_ray={**ray,**change})
            assert miss['surface_pick']['hit'] is False and 'face_index' not in miss['surface_pick']
        for args in ({'name':'PickTarget','surface_ray':ray,'uv_layer':'Missing'},
                     {'name':'TopoChanged','surface_ray':ray},
                     {'name':'PickTarget','surface_ray':ray,'vertices':True}):
            rejected=await client.call_tool('scene_info',args)
            assert rejected.is_error and rejected.structured_content['error']['outcome']=='rejected',rejected
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='surface-pick-native',expected_project=state['project_id']))['lease_id']
        await call('asset_io',action='save',path='after-picks.blend',lease_id=lease)
        assert json.loads((root/'pick-audit.json').read_text())==before
        await call('session_control',action='release',lease_id=lease)
        return {'surface_picking':'passed','misses':2,'rejections':3,'read_only_source_state':'unchanged',
                'negative_scale_and_centimetres':'passed','uv':'source corner interpolation','receipts':receipts}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('surface_pick_fixture.py'))
