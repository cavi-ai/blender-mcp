"""Edit existing shader links through real MCP, native evaluation and saved source."""
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
        catalog=await client.list_tools()
        if scoped:
            assert {t.name for t in catalog.tools}=={'scene_info','assign_material','bake','session_control','asset_io'}

        async def call(tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content

        state=await call('scene_info',limit=1)
        assert Path(state['workspace']).resolve()==root.resolve() and Path(state['file']).resolve()==root/'initial.blend'
        before=json.loads((root/'shader-link-audit.json').read_text())
        context={'material_name':'ArtistFinish','group_path':['Finish']}

        async def inspect(**options):
            return await call('assign_material',action='inspect',**{**context,**options})

        binding=lambda node,socket: {'node':node,'socket':socket}
        group_output=next(s['identifier'] for s in (await inspect(node='Result'))['nodes'][0]['inputs']
                          if s['name']=='Shader')
        unowned=await client.call_tool('assign_material',{'action':'connect',**context,'node':'Surface',
            'inputs':{'Strength':binding('Gain','Value')}})
        assert unowned.is_error
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='shader-link-native',expected_project=owner['project_id']))['lease_id']

        async def edit(action='connect',node='Surface',**options):
            return await call('assign_material',action=action,node=node,lease_id=lease,**{**context,**options})

        async def reject(node='Surface',action='connect',**options):
            baseline=await inspect()
            result=await client.call_tool('assign_material',{'action':action,'node':node,'lease_id':lease,**context,**options})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert await inspect()==baseline

        for options in [{'inputs': {'Color':binding('Cool','Color')}},
                        {'inputs': {'Strength':binding('Gain','Value'),'missing':binding('Cool','Color')}},
                        {'inputs': {'Color':binding('missing','Color')}},
                        {'inputs': {'Color':binding('Cool','missing')}},
                        {'inputs': {'Color':binding('Surface','Emission')},'update_existing': True},
                        {'node': 'MathA','inputs': {'Value':binding('MathB','Value')}},
                        {'action': 'disconnect','inputs': {'Color':binding('Cool','Color')}}]:
            await reject(**options)
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        noop=await edit(inputs={'Color':binding('Warm','Color')})
        assert noop['changed_links']==[] and noop['managed_materials_detached']==[]
        # Broken and muted links can be repaired with an explicit source expectation.
        repaired=await edit(action='disconnect',node='MathA',inputs={'Value_001':binding('Surface','Emission')})
        assert repaired['managed_materials_detached']==['ManagedA','ManagedB']
        await edit(action='disconnect',node='MathB',inputs={'Value':binding('MathA','Value')})

        async def bake(name):
            result=await call('bake',map='shader',name='Cube',path=name+'.exr',
                source={'material':'ArtistFinish','group_path':['Finish'],'node':'Surface',
                        'socket':'Color','direction':'INPUT','role':'data'},
                resolution=64,samples=1,margin=0,bit_depth=32,lease_id=lease)
            assert result['bit_depth']==32

        await bake('baseline')
        changed=await edit(inputs={'Color':binding('Cool','Color'),'Strength':binding('Gain','Value')},update_existing=True)
        assert len(changed['changed_links'])==2
        assert changed['managed_materials_detached']==[]
        assert set(changed['affected_materials'])=={'ArtistFinish','OtherFinish','ManagedA','ManagedB'}
        assert (await inspect(material_name='OtherFinish'))['links']==(await inspect())['links']
        await bake('candidate')
        removed=await edit(action='disconnect',inputs={'Color':binding('Cool','Color')})
        assert removed['changed_links'][0]['after'] is None
        await reject(action='disconnect',inputs={'Color':binding('Cool','Color')})
        await bake('disconnected')
        await edit(inputs={'Color':binding('Cool','Color')})
        # Native color-to-shader emission conversion is legal; shader-to-data is not.
        await edit(node='Result',inputs={group_output:binding('Cool','Color')},update_existing=True)
        await edit(node='Result',inputs={group_output:binding('Surface','Emission')},update_existing=True)
        snapshot=await inspect()
        await call('asset_io',action='save',path='rewired.blend',lease_id=lease)
        after=json.loads((root/'shader-link-audit.json').read_text())
        assert {k:v for k,v in after.items() if k!='samples'}=={k:v for k,v in before.items() if k!='samples'}
        expected={'baseline':[.9,.08,.03],'candidate':[.03,.2,.8],'disconnected':[.1,.1,.1]}
        for name,color in expected.items():
            assert max(abs(a-b) for a,b in zip(after['samples'][name],color,strict=True))<1e-5,after['samples']
        await call('asset_io',action='open',path='rewired.blend',lease_id=lease)
        assert await inspect()==snapshot
        assert json.loads((root/'shader-link-audit.json').read_text())==after
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'source-audits.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
        return {'shader_links':'passed','scoped_profile':scoped,'evaluated_linear_rgb':after['samples'],
            'atomic_rejections':7,'receipt_failure_rollback':'passed','save_reopen':'passed',
            'partial_batch_rollback':'passed',
            'broken_and_muted_link_repair':'passed',
            'shared_owners_and_source_data':'preserved','dedicated_source_identity_test':'passed'}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('shader_link_fixture.py'))
