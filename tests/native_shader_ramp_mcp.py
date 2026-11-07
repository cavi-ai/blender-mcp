"""Author native ramps through real scoped MCP, float bakes and saved-source checks."""
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

        state=await call('scene_info',limit=1)
        assert Path(state['workspace']).resolve()==root.resolve() and Path(state['file']).resolve()==root/'initial.blend'
        before=json.loads((root/'ramp-audit.json').read_text())
        context={'material_name':'ArtistFinish','group_path':['Finish'],'node':'Palette'}

        async def inspect(**options):return await call('assign_material',action='inspect',**{**context,**options})

        initial=await inspect();original=initial['nodes'][0]['color_ramp']
        assert original['control_schema']['min_elements']==1
        assert original['control_schema']['color']['min']==0 and original['control_schema']['color']['max']>1
        assert (await client.call_tool('assign_material',{'action':'set_ramp',**context,
            'node_settings':{'interpolation':'CONSTANT'}})).is_error
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='ramp-native',expected_project=owner['project_id']))['lease_id']

        async def edit(settings,**options):
            return await call('assign_material',action='set_ramp',lease_id=lease,node_settings=settings,**{**context,**options})

        async def reject(settings,**options):
            baseline=await inspect(**options)
            result=await client.call_tool('assign_material',{'action':'set_ramp',**context,**options,
                'node_settings':settings,'lease_id':lease})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert await inspect(**options)==baseline

        good={'position':0,'color':[0,0,0,1]}
        for settings in [{'elements':[]},{'elements':[good]*33},{'elements':[{'position':2,'color':[0,0,0,1]}]},
                         {'elements':[good,{'position':1,'color':[0,0,0]}]},
                         {'elements':[{'position':0,'color':[-.25,0,0,1]}]},
                         {'elements':[good],'interpolation':'UNKNOWN'}]:await reject(settings)
        for node in ['AnimatedRamp','NlaRamp','DrivenRamp','ReferencedRamp','AliasRamp']:
            await reject({'elements':[good]},node=node)
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        noop=await edit({key:value for key,value in original.items() if key!='control_schema'})
        assert noop['changed_ramp'] is False and noop['managed_materials_detached']==[]
        single={'position':.4,'color':[2.5,.25,.125,.4]}
        changed=await edit({'elements':[single]})
        assert changed['managed_materials_detached']==['ManagedA','ManagedB']

        async def bake(path,socket='Color'):
            result=await call('bake',map='shader',name='RampSurface',path=path+'.exr',
                source={'material':'ArtistFinish','group_path':['Finish'],'node':'Palette','socket':socket,'role':'data'},
                resolution=64,samples=1,margin=0,bit_depth=32,lease_id=lease)
            assert result['bit_depth']==32

        await bake('single');await bake('alpha','Alpha')
        low=[.125,.25,.5,1];high=[.875,.75,.25,1]
        elements=[{'position':0,'color':low},{'position':1,'color':high}]
        await edit({'elements':elements,'interpolation':'LINEAR','color_mode':'RGB'})
        await bake('linear')
        await call('asset_io',action='save',path='linear.blend',lease_id=lease)
        linear=json.loads((root/'ramp-audit.json').read_text())
        assert linear['bakes']['linear']['native_evaluation_error']<.002,linear['bakes']['linear']
        for name,expected in [('single',single['color'][:3]),('alpha',[.4]*3)]:
            for key in ['min','max']:
                assert max(abs(a-b) for a,b in zip(linear['bakes'][name][key],expected,strict=True))<1e-5,linear['bakes'][name]
        await edit({'elements':[{'position':0,'color':low},{'position':.375,'color':high},
                               {'position':1,'color':[.2,.3,.4,1]}],'interpolation':'CONSTANT'})
        await bake('constant')
        await call('asset_io',action='save',path='constant.blend',lease_id=lease)
        constant=json.loads((root/'ramp-audit.json').read_text())['bakes']['constant']['row']
        assert max(abs(a-b) for i,rgb in enumerate(constant) for a,b in zip(rgb,low[:3] if (i+.5)/64<.375 else high[:3],strict=True))<1e-5
        # Native single-stop, equal-position and full-capacity collections all remain authorable.
        await edit({'elements':[{'position':.5,'color':low},{'position':.5,'color':high}]})
        await edit({'elements':[{'position':i/31,'color':[i/31,.2,.3,1]} for i in range(32)]})
        assert len((await inspect())['nodes'][0]['color_ramp']['elements'])==32
        await edit({'elements':[{'position':.4,'color':[0,.123456789,2.5,.4]}]})
        tiny=await edit({'elements':[{'position':.4,'color':[1e-9,.123456789,2.5,.4]}]})
        assert tiny['changed_ramp'] and 0<tiny['nodes'][0]['color_ramp']['elements'][0]['color'][0]<2e-9
        precision=await inspect()
        await call('asset_io',action='save',path='precision.blend',lease_id=lease)
        await call('asset_io',action='open',path='precision.blend',lease_id=lease)
        assert await inspect()==precision
        for mode in ['EASE','CARDINAL','B_SPLINE']:
            assert (await edit({'interpolation':mode}))['nodes'][0]['color_ramp']['interpolation']==mode
        await edit({'elements':elements,'interpolation':'LINEAR','color_mode':'HSV','hue_interpolation':'FAR'})
        await bake('hsv')
        snapshot=await inspect()
        await call('asset_io',action='save',path='ramps.blend',lease_id=lease)
        after=json.loads((root/'ramp-audit.json').read_text())
        assert before['guards']==after['guards'] and before['plane']==after['plane']
        assert after['bakes']['hsv']['native_evaluation_error']<.005,after['bakes']['hsv']
        await call('asset_io',action='open',path='ramps.blend',lease_id=lease)
        assert await inspect()==snapshot
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'ramp-evidence.json').write_text(json.dumps(
                {'native_schema':original['control_schema'],'linear':linear,'final':after},indent=2)+'\n')
        return {'ramps':'passed','scoped_profile':scoped,'hdr_and_alpha':'passed',
            'linear_error':linear['bakes']['linear']['native_evaluation_error'],
            'hsv_error':after['bakes']['hsv']['native_evaluation_error'],'constant_steps':'passed',
            'native_stop_counts':[1,2,32],'duplicate_positions':'passed','animation_and_driver_guards':5,
            'small_float_edit':'passed',
            'receipt_rollback':'passed','save_reopen':'passed','dedicated_source_identity_test':'passed'}


if __name__=='__main__':main(exercise,Path(__file__).with_name('shader_ramp_fixture.py'))
