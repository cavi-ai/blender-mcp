"""Discover and author native procedural nodes through scoped MCP and actual bakes."""
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
        before=json.loads((root/'shader-link-audit.json').read_text())
        context={'material_name':'ArtistFinish','group_path':['Finish']}

        async def inspect(**options):
            return await call('assign_material',action='inspect',**{**context,**options})

        original=await inspect()
        types=await call('assign_material',action='node_types',limit=1000,**context)
        kinds={row['type'] for row in types['node_types']}
        assert {'ShaderNodeMath','ShaderNodeTexNoise'}<=kinds
        exact=await call('assign_material',action='node_types',node_type='ShaderNodeMath',**context)
        assert 'MULTIPLY' in exact['node_types'][0]['control_schema']['operation']['items']
        assert (await call('assign_material',action='node_types',limit=1,offset=1,**context))['node_types']==types['node_types'][1:2]
        assert await inspect()==original
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        unowned=await client.call_tool('assign_material',{'action':'create_node','node':'Denied',
            'node_type':'ShaderNodeMath',**context})
        assert unowned.is_error
        owner=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='shader-node-native',expected_project=owner['project_id']))['lease_id']

        async def material(action,**options):
            return await call('assign_material',action=action,lease_id=lease,**{**context,**options})

        for options in [{'node':'Surface'}, {'node':'BadEnum','node_settings':{'operation':'UNKNOWN'}},
                        {'node':'BadBatch','node_settings':{'operation':'MULTIPLY','missing':True}},
                        {'node':'BadBool','node_settings':{'use_clamp':1}},
                        {'node':'WrongTree','node_type':'CompositorNodeBlur'}]:
            result=await client.call_tool('assign_material',{'action':'create_node','node_type':'ShaderNodeMath',
                **context,'lease_id':lease,**options})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert await inspect()==original
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        noise=await material('create_node',node='WearNoise',node_type='ShaderNodeTexNoise',
            node_settings={'noise_dimensions':'4D','normalize':True})
        assert noise['managed_materials_detached']==['ManagedA','ManagedB']
        multiply=await material('create_node',node='WearGain',node_type='ShaderNodeMath',
            node_settings={'operation':'MULTIPLY','use_clamp':False})
        assert multiply['created_node']['settings']=={'operation':'MULTIPLY','use_clamp':False}
        assert multiply['nodes'][0]['bl_idname']=='ShaderNodeMath'
        uv=await material('create_node',node='AuthorUV',node_type='ShaderNodeUVMap',
            node_settings={'uv_map':next(iter(before['uvs']))})
        assert uv['nodes'][0]['uv_map']==next(iter(before['uvs']))
        await material('connect',node='WearNoise',inputs={'Vector':{'node':'AuthorUV','socket':'UV'}})
        math_inputs=[s['identifier'] for s in multiply['nodes'][0]['inputs'] if s['editable'] and s['enabled']]
        assert len(math_inputs)>=2
        await material('set_inputs',node='WearGain',inputs={math_inputs[1]:.5})
        await material('connect',node='WearGain',inputs={math_inputs[0]:{'node':'WearNoise','socket':'Fac'}})
        await material('connect',node='Surface',inputs={'Color':{'node':'WearGain','socket':'Value'}},update_existing=True)
        results={}
        for path,node,socket,direction in [('noise','WearNoise','Fac','OUTPUT'),('candidate','Surface','Color','INPUT')]:
            results[path]=await call('bake',map='shader',name='Cube',path=path+'.exr',
                source={'material':'ArtistFinish','group_path':['Finish'],'node':node,'socket':socket,'direction':direction,'role':'data'},
                resolution=64,samples=1,margin=0,bit_depth=32,lease_id=lease)
            assert results[path]['bit_depth']==32
        snapshot=await inspect()
        root_snapshot=await inspect(group_path=[])
        output=await material('create_node',group_path=[],node='AlternativeOutput',node_type='ShaderNodeOutputMaterial')
        assert output['nodes'][0]['is_active_output'] is False
        # Existing output stays active; its links and settings remain the same.
        assert (await inspect(group_path=[],node='Output'))['links']==[l for l in root_snapshot['links'] if l['to_node']=='Output']
        assert (await inspect(group_path=[],node='Output'))['nodes'][0]['is_active_output'] is True
        await call('asset_io',action='save',path='procedural-nodes.blend',lease_id=lease)
        after=json.loads((root/'shader-link-audit.json').read_text())
        assert {k:v for k,v in after.items() if k!='samples'}=={k:v for k,v in before.items() if k!='samples'}
        sampled=json.loads((root/'shader-node-samples.json').read_text())
        assert sampled['maximum_abs_error']<1e-5 and sampled['noise_range'][1]>.01,sampled
        await call('asset_io',action='open',path='procedural-nodes.blend',lease_id=lease)
        assert await inspect()==snapshot
        await call('session_control',action='release',lease_id=lease)
        await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'source-audits.json').write_text(json.dumps({'before':before,'after':after},indent=2)+'\n')
        return {'shader_nodes':'passed','scoped_profile':scoped,'available_types':types['total'],
            'procedural_samples':sampled,'creation_and_output_rollback':'passed',
            'source_data':'preserved','save_reopen':'passed','dedicated_source_identity_test':'passed'}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('shader_node_fixture.py'))
