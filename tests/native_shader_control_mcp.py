"""Update existing shader controls through scoped MCP and evaluated float bakes."""
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
            result=await client.call_tool(tool,args);assert not result.is_error,result
            return result.structured_content
        source=await call('scene_info',limit=1)
        assert Path(source['workspace']).resolve()==root.resolve() and Path(source['file']).resolve()==root/'initial.blend'
        context={'material_name':'ArtistFinish','group_path':['Finish']}
        async def inspect(node,**options):
            return await call('assign_material',action='inspect',node=node,**{**context,**options})
        original=await inspect('ExistingNoise');schema=original['nodes'][0]['control_schema']
        assert '4D' in schema['noise_dimensions']['items'] and schema['normalize']['type']=='BOOLEAN'
        assert original['nodes'][0]['settings']['noise_dimensions']=='3D'
        assert (await client.call_tool('assign_material',{'action':'set_node',**context,'node':'ExistingNoise',
            'node_settings':{'noise_dimensions':'4D'}})).is_error
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='node-controls',expected_project=state['project_id']))['lease_id']
        async def edit(node,settings,**options):
            return await call('assign_material',action='set_node',node=node,node_settings=settings,
                lease_id=lease,**{**context,**options})
        async def reject(node,settings,action='set_node'):
            before=await inspect(node)
            result=await client.call_tool('assign_material',{'action':action,**context,'node':node,
                'node_settings':settings,'lease_id':lease})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert await inspect(node)==before
        for settings in [{'normalize':'true'},{'noise_dimensions':'UNKNOWN'},
            {'normalize':True,'unknown':1},{'image':'map.png'},{'name':'Renamed'}]:
            await reject('ExistingNoise',settings)
        await reject('GuardNoise',{'normalize':False})
        for name in ['AnimatedRamp','NlaRamp','DrivenRamp','ReferencedRamp','AliasRamp']:
            await reject(name,{'elements':[{'position':0,'color':[0,0,0,1]}]},action='set_ramp')
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        noop=await edit('ExistingNoise',{'noise_dimensions':'3D','normalize':False})
        assert noop['changed_settings']=={} and noop['managed_materials_detached']==[]
        async def bake(node,path):
            result=await call('bake',map='shader',name='RampSurface',path=path+'.exr',
                source={'material':'ArtistFinish','group_path':['Finish'],'node':node,'socket':'Fac' if node=='ExistingNoise' else 'Value','role':'data'},
                resolution=64,samples=1,margin=0,bit_depth=32,lease_id=lease)
            assert result['bit_depth']==32
        await bake('ExistingNoise','controls-baseline')
        before=await inspect('ExistingMath')
        changed=await edit('ExistingNoise',{'noise_dimensions':'4D','normalize':True})
        assert changed['managed_materials_detached']==['ManagedA','ManagedB']
        assert set(changed['changed_settings'])=={'noise_dimensions','normalize'}
        assert changed['nodes'][0]['settings']['noise_dimensions']=='4D'
        old_defaults={s['identifier']:s['value'] for s in original['nodes'][0]['inputs']}
        new_defaults={s['identifier']:s['value'] for s in changed['nodes'][0]['inputs']}
        assert all(new_defaults[key]==value for key,value in old_defaults.items())
        await edit('ExistingUV',{'uv_map':'AltUV'})
        math=await edit('ExistingMath',{'operation':'MULTIPLY'})
        assert math['changed_settings']['operation']=={'before':'ADD','after':'MULTIPLY'}
        assert math['links']==before['links']
        assert [s['value'] for s in math['nodes'][0]['inputs']]==[s['value'] for s in before['nodes'][0]['inputs']]
        # References to another property do not prevent independent native controls.
        await edit('GuardNoise',{'noise_dimensions':'4D'})
        await bake('ExistingNoise','controls-noise');await bake('ExistingMath','controls-math')
        output=await edit('AlternativeOutput',{'is_active_output':True},group_path=[])
        assert {row['node'] for row in output['changed_active_outputs']}=={'Output','AlternativeOutput'}
        snapshot=await inspect('ExistingNoise');math_snapshot=await inspect('ExistingMath')
        await call('asset_io',action='save',path='controls.blend',lease_id=lease)
        evidence=json.loads((root/'control-bakes.json').read_text())
        assert evidence['mode_change_max_difference']>.001 and evidence['multiply_max_error']<1e-5,evidence
        await call('asset_io',action='open',path='controls.blend',lease_id=lease)
        assert await inspect('ExistingNoise')==snapshot and await inspect('ExistingMath')==math_snapshot
        assert (await inspect('AlternativeOutput',group_path=[]))['nodes'][0]['is_active_output']
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'control-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        return {'existing_shader_controls':'passed','scoped_profile':scoped,'bakes':evidence,
            'receipt_and_active_output_rollback':'passed','animation_alias_and_ramp_regression':'passed','save_reopen':'passed'}


if __name__=='__main__':main(exercise,Path(__file__).with_name('shader_control_fixture.py'))
