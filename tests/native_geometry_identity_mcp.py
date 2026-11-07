"""A camera-stable render must reject stale geometry, instance and UV state."""
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root,env,parameters=None,editor_parameters=None):
    scoped=parameters is not None and editor_parameters is not None
    default=StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with (stdio_client(parameters or default) as streams,ClientSession(*streams) as review,
                stdio_client(editor_parameters or default) as edits,ClientSession(*edits) as editor):
        await review.initialize()
        await editor.initialize()

        async def call(client,tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content

        state=await call(review,'scene_info',limit=1)
        assert Path(state['workspace']).resolve()==root.resolve() and Path(state['file']).resolve()==root/'initial.blend'
        assert state['source_state']['saved_source']['sha256']==hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        owner=await call(review,'session_control',action='inspect')
        lease=(await call(review,'session_control',action='claim',owner='geometry-identity-native',expected_project=owner['project_id']))['lease_id']

        async def render(name):
            capture=await call(review,'scene_edit',action='render',lease_id=lease,render={
                'path':name+'.png','camera':'Review','width':96,'height':32,'frame':1,
                'samples':1,'threads':2,'transparent':True,'denoise':False,'view_transform':'Standard'})
            identity=capture.get('geometry_identity')
            assert identity and identity['available'],'Render geometry identity is missing'
            assert capture['bit_depth']==16 and capture['sha256']==hashlib.sha256((root/(name+'.png')).read_bytes()).hexdigest()
            return capture

        baseline=await render('identity-baseline')
        await call(review,'asset_io',action='save',path='before.blend',lease_id=lease)
        await call(review,'asset_io',action='save',path='before-clean.blend',lease_id=lease)
        before=json.loads((root/'audit.json').read_text())
        reference=json.loads((root/'references.json').read_text())['Foreground']
        query={key:reference[key] for key in ('camera','pixel','image_size')}
        query.update(evaluated=True,max_distance_m=20,
            expected_projection_sha256=baseline['camera_projection']['sha256'],
            expected_geometry_sha256=baseline['geometry_identity']['sha256'])

        async def pick(name='Foreground',current=query):
            result=await call(review,'scene_info',surface_ray=current,uv_layer='UVMap')
            assert result['name']==name and result['surface_pick']['hit'],result
            assert result['surface_pick']['camera_query']['geometry_identity_checked'],result
            return result

        initial=await pick()
        assert not (await call(review,'scene_info',limit=1))['source_state']['dirty']

        async def reject():
            result=await review.call_tool('scene_info',{'surface_ray':query})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert any('geometry changed' in getattr(item,'text','').lower() for item in result.content),result

        await call(editor,'object_edit',action='transform',name='Foreground',location=[3,0,1],lease_id=lease)
        await reject()
        unchecked={**query}
        unchecked.pop('expected_geometry_sha256')
        discovery=await call(review,'scene_info',surface_ray=unchecked)
        assert discovery['name']=='Rear' and not discovery['surface_pick']['camera_query']['geometry_identity_checked'],discovery
        moved=await render('identity-moved')
        assert moved['camera_projection']['sha256']==baseline['camera_projection']['sha256']
        assert moved['geometry_identity']['sha256']!=baseline['geometry_identity']['sha256']
        fresh=await pick('Rear',{**query,'expected_geometry_sha256':moved['geometry_identity']['sha256']})
        await call(review,'asset_io',action='save',path='moved.blend',lease_id=lease)
        samples=json.loads((root/'identity-samples.json').read_text())
        a,b=samples['identity-baseline'],samples['identity-moved']
        assert a['bit_depth']==b['bit_depth']==16 and a['rgba'][1]>.8 and b['rgba'][0]>.8,samples
        assert a['rgba'][0]<.1 and b['rgba'][1]<.1,samples
        await call(editor,'object_edit',action='transform',name='Foreground',location=[0,0,1],lease_id=lease)
        await pick()
        await call(editor,'object_edit',action='transform',name='InstancePlacement',location=[5,0,0],lease_id=lease)
        await reject()
        await call(editor,'object_edit',action='transform',name='InstancePlacement',location=[4,0,0],lease_id=lease)
        await pick()
        await call(editor,'mesh_edit',action='uv_transform',name='Foreground',uv_layer='UVMap',
            uv_transform={'faces':[0],'offset':[.125,0]},lease_id=lease)
        await reject()
        await call(editor,'mesh_edit',action='uv_transform',name='Foreground',uv_layer='UVMap',
            uv_transform={'faces':[0],'offset':[-.125,0]},lease_id=lease)
        restored=await pick()
        drift=await call(review,'scene_edit',action='render',lease_id=lease,render={
            'path':'identity-drift.png','camera':'Review','width':96,'height':32,'frame':1,
            'samples':1,'threads':2,'transparent':True,'denoise':False,'view_transform':'Standard'})
        assert drift['bit_depth']==16 and not drift['geometry_identity']['available'],drift
        assert 'geometry changed during render' in drift['geometry_identity']['reason'].lower(),drift
        assert drift['sha256']==hashlib.sha256((root/'identity-drift.png').read_bytes()).hexdigest()
        await call(editor,'object_edit',action='transform',name='Foreground',location=[0,0,1],lease_id=lease)
        await pick()
        await call(review,'asset_io',action='save',path='restored.blend',lease_id=lease)
        assert json.loads((root/'audit.json').read_text())==before
        await call(review,'session_control',action='release',lease_id=lease)
        evidence=os.environ.get('CAVI_NATIVE_EVIDENCE')
        if evidence:
            for name in ('identity-baseline','identity-moved','identity-drift'):
                destination=Path(evidence)/(name+'.png')
                assert not destination.exists()
                shutil.copy2(root/(name+'.png'),destination)
        return {'geometry_identity':'passed','scoped_profiles':scoped,'rejected_changes':3,
            'restored_geometry':'accepted','task_owned_geometry':'restored','captures':[baseline,moved],
            'pixel_samples':samples,'initial':initial,'fresh':fresh,'restored':restored,
            'changed_during_render':drift}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('geometry_identity_fixture.py'))
