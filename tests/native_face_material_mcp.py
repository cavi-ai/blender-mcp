"""Assign source-face finishes through MCP without changing rigged surface data."""
import hashlib
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root,env,parameters=None):
    scoped=parameters is not None
    parameters=parameters or StdioServerParameters(command=sys.executable,
        args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(parameters) as streams,ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content

        state=await call('scene_info',limit=1)
        assert Path(state['workspace']).resolve()==root.resolve() and Path(state['file']).resolve()==root/'initial.blend'
        assert state['source_state']['saved_source']['sha256']==hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='face-material-native',
                          expected_project=owner['project_id']))['lease_id']
        sequence=0

        async def snapshot():
            nonlocal sequence
            sequence+=1
            await call('asset_io',action='save',path=f'finishes-{sequence}.blend',lease_id=lease)
            return {key:json.loads((root/f'{key}-audit.json').read_text()) for key in ('vertex','density')}

        before=await snapshot()
        page=await call('scene_info',name='TileGrid',faces=True)
        args={'action':'assign_faces','name':'TileGrid','material_name':'TrimFinish','face_indices':[0],
              'expected_mesh_sha256':page['mesh_sha256'],'lease_id':lease}
        # Establish the advertised production path before testing refusal reasons.
        result=await call('mesh_edit',**args)
        receipt=result['face_material']
        assert receipt['face_indices']==[0] and receipt['material']=='TrimFinish'
        assert receipt['slot']==2 and receipt['slot_created'] and receipt['changed_faces']==1,receipt
        assert receipt['previous_slots']==[0]
        assert receipt['mesh_sha256_before']==page['mesh_sha256']!=receipt['mesh_sha256_after']
        after=await snapshot()
        old,new=before['vertex']['objects']['TileGrid'],after['vertex']['objects']['TileGrid']
        assert new['slots']==[2,1] and new['materials']==old['materials']+['TrimFinish']
        assert all(new[k]==v for k,v in old.items() if k not in ('slots','materials'))
        assert all(after['vertex'][k]==v for k,v in before['vertex'].items() if k!='objects')
        assert all(after['vertex']['objects'][k]==v for k,v in before['vertex']['objects'].items() if k!='TileGrid')
        assert all(after['density'][k]==v for k,v in before['density'].items() if k not in ('geometry','slots','materials'))
        current={**args,'expected_mesh_sha256':receipt['mesh_sha256_after']}
        for invalid in [{'face_indices':[0,0]},{'face_indices':[20]},
                        {'expected_mesh_sha256':page['mesh_sha256']},{'name':'SharedA'},
                        {'material_name':'MissingFinish'}]:
            result=await client.call_tool('mesh_edit',{**current,**invalid})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert not (await call('scene_info',limit=1))['source_state']['dirty']
            assert await snapshot()==after
        reuse=(await call('mesh_edit',**{**current,'face_indices':[1]}))['face_material']
        assert reuse['slot']==2 and not reuse['slot_created'] and reuse['previous_slots']==[1]
        assert reuse['changed_faces']==1
        final=await snapshot()
        assert final['vertex']['objects']['TileGrid']=={**new,'slots':[2,2]}
        assert all(final['density'][k]==v for k,v in after['density'].items() if k not in ('geometry','slots'))
        unchanged=(await call('mesh_edit',**{**current,'face_indices':[0,1],
            'expected_mesh_sha256':reuse['mesh_sha256_after']}))['face_material']
        assert unchanged['changed_faces']==0 and unchanged['mesh_sha256_before']==unchanged['mesh_sha256_after']
        # Owned mutations conservatively mark source state dirty even for a no-op.
        assert await snapshot()==final
        await call('asset_io',action='open',path=f'finishes-{sequence}.blend',lease_id=lease)
        reopened=await call('scene_info',name='TileGrid',faces=True)
        assert [f['material_index'] for f in reopened['faces']]==[2,2]
        assert await snapshot()==final
        await call('session_control',action='release',lease_id=lease)
        evidence=os.environ.get('CAVI_NATIVE_EVIDENCE')
        if evidence:
            (Path(evidence)/'source-audits.json').write_text(json.dumps({'before':before,'after':after,'final':final},indent=2)+'\n')
        return {'face_materials':'passed','scoped_profile':scoped,'preflight_rejections':5,
                'rig_uv_shape_keys_context':'preserved','save_reopen':'passed','receipts':[receipt,reuse,unchanged]}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('face_material_fixture.py'))
