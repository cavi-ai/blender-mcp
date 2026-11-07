"""One real MCP case discovers scene surfaces without knowing target names."""
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


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
        before=json.loads((root/'audit.json').read_text())
        references=json.loads((root/'references.json').read_text())
        samples=json.loads((root/'samples.json').read_text())
        assert (root/'review.png').read_bytes()[24]==16
        hits={}
        for name,reference in references.items():
            assert samples[name][reference['channel']]>.8 and samples[name][3]>.95,samples
            query={k:reference[k] for k in ('camera','pixel','image_size')}
            query.update(evaluated=True,max_distance_m=20)
            result=await call('scene_info',surface_ray=query,uv_layer='UVMap')
            pick=result['surface_pick']
            assert result['scope']=='scene_surface_pick' and result['name']==name and pick['hit'],result
            assert math.dist(pick['position_world'],reference['world'])<2e-5,result
            if name=='Generated':
                assert not pick['source_mapping']['available'] and 'face_index' not in pick and 'uv' not in pick,result
            else:
                assert pick['source_mapping']['available'] and math.dist(pick['uv']['position'],[.3,.4])<2e-6,result
            hits[name]=result
        assert hits['Foreground']['surface_pick']['material']=={'index':0,'name':'ObjectFinish','link':'OBJECT'}
        assert hits['Foreground']['surface_pick']['geometry_considered']['triangles']==4,hits['Foreground']
        finish=await call('assign_material',action='inspect',material_name=hits['Foreground']['surface_pick']['material']['name'])
        assert finish['material']=='ObjectFinish' and any(n['type']=='EMISSION' for n in finish['nodes']),finish
        if scoped:
            denied=await client.call_tool('assign_material',{'action':'set_inputs','material_name':'ObjectFinish',
                'node':'Emission','inputs':{'Color':[0,0,0,1]}})
            assert denied.is_error and any('excluded' in getattr(i,'text','').lower() for i in denied.content),denied
        placed=hits['Prototype']['surface_pick']['instance']
        assert placed['is_instance'] and placed['parent']=='InstancePlacement',placed
        assert placed['matrix_world'][0]==[-1.5,0.,0.,4.],placed
        query={**hits['Foreground']['surface_pick']['camera_query']['query']}
        named=await call('scene_info',name='Foreground',surface_ray=query,uv_layer='UVMap')
        assert named['mesh_sha256']==hits['Foreground']['mesh_sha256']
        assert math.dist(named['surface_pick']['uv']['position'],[.3,.4])<2e-6,named
        for change in ({'pixel':[0,0]},{'max_distance_m':.05}):
            miss=await call('scene_info',surface_ray={**query,**change})
            assert not miss['surface_pick']['hit'],miss
        rejected=await client.call_tool('scene_info',{'surface_ray':{**query,'evaluated':False}})
        assert rejected.is_error and rejected.structured_content['error']['outcome']=='rejected'
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='scene-pick-native',expected_project=owner['project_id']))['lease_id']
        await call('asset_io',action='save',path='after.blend',lease_id=lease)
        assert json.loads((root/'audit.json').read_text())==before
        await call('session_control',action='release',lease_id=lease)
        evidence=os.environ.get('CAVI_NATIVE_EVIDENCE')
        if evidence:
            destination=Path(evidence)/'review.png'
            assert not destination.exists()
            shutil.copy2(root/'review.png',destination)
        return {'scene_surface_picking':'passed','native_png_depth':16,'hits':hits,
            'samples':samples,'material_inspection':finish,'scoped_profile_tested':scoped,
            'named_query_parity':'passed','misses':2,'source_state':'unchanged by queries'}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('scene_pick_fixture.py'))
