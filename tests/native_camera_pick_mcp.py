"""One rendered-pixel case with real projection receipts and scoped native calls."""
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
        references=json.loads((root/'camera-reference.json').read_text())
        initial=json.loads((root/'initial-camera-sample.json').read_text())
        assert initial['bit_depth']==16 and initial['rgba'][3]>.95 and initial['rgba'][0]>.5,initial
        first={**references['Perspective'],'max_distance_m':1,'evaluated':True}
        first={k:v for k,v in first.items() if k not in ('position_world','uv')}
        percent=await call('scene_info',name='PickTarget',surface_ray=first,uv_layer='SourceUV')
        assert percent['surface_pick']['hit'] and not percent['surface_pick']['camera_query']['identity_checked']
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='camera-pixel-native',expected_project=owner['project_id']))['lease_id']
        if scoped:
            excluded=await client.call_tool('scene_edit',{'action':'world','world':{'name':'ExcludedWorld'},'lease_id':lease})
            assert excluded.is_error and any('excluded' in getattr(item,'text','').lower() for item in excluded.content)
        renders={}
        for name in references:
            result=await call('scene_edit',action='render',render={'path':name+'.png','camera':name,
                'width':80,'height':60,'samples':1,'threads':2,'frame':3,'transparent':True,
                'denoise':False,'view_transform':'Standard'},lease_id=lease)
            assert result['bit_depth']==16 and result['camera_projection']['available'],result
            assert result['sha256']==hashlib.sha256((root/(name+'.png')).read_bytes()).hexdigest()
            renders[name]=result
        await call('asset_io',action='save',path='measured.blend',lease_id=lease)
        await call('asset_io',action='save',path='before-queries.blend',lease_id=lease)
        before=json.loads((root/'camera-audit.json').read_text())
        samples=json.loads((root/'camera-samples.json').read_text())
        receipts={}
        for name,reference in references.items():
            assert samples[name]['bit_depth']==16 and samples[name]['rgba'][3]>.95 and samples[name]['rgba'][0]>.5,samples[name]
            query={k:v for k,v in reference.items() if k not in ('position_world','uv')}
            query.update(max_distance_m=1,evaluated=True,expected_projection_sha256=renders[name]['camera_projection']['sha256'])
            result=await call('scene_info',name='PickTarget',surface_ray=query,uv_layer='SourceUV')
            hit=result['surface_pick']
            assert hit['hit'] and hit['camera_query']['identity_checked'] and hit['face_index']==0,hit
            assert all(math.isclose(a,b,abs_tol=1e-5) for a,b in zip(hit['position_world'],reference['position_world'],strict=True)),hit
            assert all(math.isclose(a,b,abs_tol=2e-6) for a,b in zip(hit['uv']['position'],[.34,.5],strict=True)),hit
            legacy=await call('scene_info',name='PickTarget',surface_ray=hit['ray'])
            assert math.dist(legacy['surface_pick']['position_world'],hit['position_world'])<1e-6
            receipts[name]=result
        query=receipts['Perspective']['surface_pick']['camera_query']['query']
        for name in ('NearClip','FarClip'):
            miss=await call('scene_info',name=name,surface_ray=query)
            assert not miss['surface_pick']['hit'],miss
        for change in ({'expected_projection_sha256':'0'*64},{'image_size':[81,60]},
                       {'pixel':[80,0]},{'camera':'Panorama','expected_projection_sha256':None}):
            rejected=await client.call_tool('scene_info',{'name':'PickTarget','surface_ray':{**query,**change}})
            assert rejected.is_error and rejected.structured_content['error']['outcome']=='rejected',rejected
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        await call('asset_io',action='save',path='after-queries.blend',lease_id=lease)
        assert json.loads((root/'camera-audit.json').read_text())==before
        previous=renders['Perspective']['camera_projection']
        await call('scene_edit',action='camera',camera={'name':'Perspective',
            'location':[row[3] for row in previous['matrix_world'][:3]],
            'target':references['Perspective']['position_world'],
            'projection':'perspective','focal_length_mm':55,'sensor_width_mm':36,
            'clip_start':.1,'clip_end':20,'shift':[.11,-.08]},lease_id=lease)
        stale=await client.call_tool('scene_info',{'name':'PickTarget','surface_ray':query})
        assert stale.is_error and stale.structured_content['error']['outcome']=='rejected',stale
        updated=await call('scene_edit',action='render',render={'path':'Perspective-Updated.png',
            'camera':'Perspective','width':80,'height':60,'samples':1,'threads':2,'frame':3,
            'transparent':True,'denoise':False,'view_transform':'Standard'},lease_id=lease)
        assert updated['bit_depth']==16 and updated['camera_projection']['available'],updated
        assert updated['sha256']==hashlib.sha256((root/'Perspective-Updated.png').read_bytes()).hexdigest()
        assert updated['camera_projection']['sha256']!=previous['sha256']
        fresh=await call('scene_info',name='PickTarget',uv_layer='SourceUV',surface_ray={**query,
            'expected_projection_sha256':updated['camera_projection']['sha256']})
        assert fresh['surface_pick']['hit'] and fresh['surface_pick']['camera_query']['identity_checked'],fresh
        assert math.dist(fresh['surface_pick']['uv']['position'],[.34,.5])<2e-6,fresh
        renders['Perspective-Updated']=updated
        await call('session_control',action='release',lease_id=lease)
        evidence=os.environ.get('CAVI_NATIVE_EVIDENCE')
        if evidence:
            folder=Path(evidence)
            folder.mkdir(parents=True,exist_ok=True)
            for name in renders:
                destination=folder/(name+'.png')
                assert not destination.exists()
                shutil.copy2(root/(name+'.png'),destination)
        return {'camera_pixel_picking':'passed','native_png_depth':16,'projection_receipts':renders,
            'scoped_profile_tested':scoped,
            'source_and_camera_state':'unchanged by queries','clip_misses':2,'rejections':4,
            'stale_camera_lifecycle':{'old_projection_rejected':True,'fresh_receipt':fresh},
            'percentage_raster':'passed','receipts':receipts,'pixel_samples':samples}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('camera_pick_fixture.py'))
