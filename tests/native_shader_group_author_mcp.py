"""Author a typed material function entirely through scoped MCP, then save and reuse it."""
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
        async def inspect(**options):return await call('assign_material',action='inspect',**{**context,**options})
        types=await call('assign_material',action='node_types',node_type='ShaderNodeGroup',**context)
        assert 'object' in types['node_types'][0]['resource_schema']['node_tree']['type']
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='shader-function-author',expected_project=state['project_id']))['lease_id']
        original=await inspect()
        failures=[]
        bad=[{'name':'SurfaceGraph'},
            {'name':'BadType','interface':[{'name':'X','in_out':'INPUT','socket_type':'NodeSocketMissing'}]},
            {'name':'BadDefault','interface':[{'name':'X','in_out':'INPUT','socket_type':'NodeSocketFloat','default_value':True}]},
            {'name':'BadRange','interface':[{'name':'X','in_out':'INPUT','socket_type':'NodeSocketFloat','min_value':2,'max_value':1}]}]
        for spec in bad:
            result=await client.call_tool('assign_material',{'action':'create_node',**context,'node':'Rejected',
                'node_type':'ShaderNodeGroup','node_settings':{'node_tree':spec},'lease_id':lease})
            assert result.is_error and await inspect()==original
            failures.append(spec['name'])
        spec={'name':'McpFunction','interface':[
            {'name':'Signal','in_out':'INPUT','socket_type':'NodeSocketFloat','default_value':-.2,
                'min_value':-4,'max_value':4,'description':'Signed signal'},
            {'name':'Direction','in_out':'INPUT','socket_type':'NodeSocketVector','default_value':[1.125,-2.25,3.5]},
            {'name':'Tint','in_out':'INPUT','socket_type':'NodeSocketColor','default_value':[.123456789,.25,1.5,.4]},
            {'name':'Result','in_out':'OUTPUT','socket_type':'NodeSocketFloat'},
            {'name':'Surface','in_out':'OUTPUT','socket_type':'NodeSocketShader'}]}
        created=await call('assign_material',action='create_node',**context,node='AuthoredA',node_type='ShaderNodeGroup',
            node_settings={'node_tree':spec},lease_id=lease)
        resource=created['created_node']['resources']['node_tree'];assert resource['created'] and resource['name']=='McpFunction'
        interface=created['nodes'][0]['group_interface'];assert len(interface)==5
        declared=next(s for s in interface if s['name']=='Signal' and s['in_out']=='INPUT')
        assert declared['min_value']==-4 and declared['max_value']==4,interface
        inner={**context,'group_path':['Finish','AuthoredA']}
        available=await call('assign_material',action='node_types',**inner,limit=1000)
        assert {'NodeGroupInput','NodeGroupOutput'}<={row['type'] for row in available['node_types']}
        reports={}
        for name,kind,settings in [('Input','NodeGroupInput',{}),('Output','NodeGroupOutput',{}),
            ('Gain','ShaderNodeMath',{'operation':'MULTIPLY'})]:
            result=await call('assign_material',action='create_node',**inner,node=name,node_type=kind,
                node_settings=settings,lease_id=lease)
            reports[name]=result['nodes'][0]
        signal=next(s['identifier'] for s in reports['Input']['outputs'] if s['name']=='Signal')
        target=next(s['identifier'] for s in reports['Output']['inputs'] if s['name']=='Result')
        await call('assign_material',action='set_inputs',**inner,node='Gain',
            inputs={reports['Gain']['inputs'][1]['identifier']:.5},lease_id=lease)
        await call('assign_material',action='connect',**inner,node='Gain',
            inputs={reports['Gain']['inputs'][0]['identifier']:{'node':'Input','socket':signal}},lease_id=lease)
        await call('assign_material',action='connect',**inner,node='Output',
            inputs={target:{'node':'Gain','socket':reports['Gain']['outputs'][0]['identifier']}},lease_id=lease)
        await call('assign_material',action='create_node',**context,node='AuthoredB',node_type='ShaderNodeGroup',
            node_settings={'node_tree':resource['name']},lease_id=lease)
        async def signal_value(node,value):
            report=(await inspect(node=node))['nodes'][0]
            key=next(s['identifier'] for s in report['inputs'] if s['name']=='Signal')
            await call('assign_material',action='set_inputs',**context,node=node,inputs={key:value},lease_id=lease)
        await signal_value('AuthoredB',2.5)
        async def bake(node,path):
            report=(await inspect(node=node))['nodes'][0]
            key=next(s['identifier'] for s in report['outputs'] if s['name']=='Result')
            await call('bake',map='shader',name='RampSurface',path=path+'.exr',resolution=64,samples=1,margin=0,
                bit_depth=32,lease_id=lease,source={'material':'ArtistFinish','group_path':['Finish'],
                    'node':node,'socket':key,'role':'data'})
        await bake('AuthoredA','authored-a');await bake('AuthoredB','authored-b')
        await call('asset_io',action='save',path='authored-function.blend',lease_id=lease)
        await call('asset_io',action='open',path='initial.blend',lease_id=lease)
        library=await call('asset_library',action='inspect',kind='node_groups',path='authored-function.blend')
        assert resource['name'] in library['names'] and not set(failures[1:])&set(library['names'])
        appended=await call('asset_library',action='append',kind='node_groups',path='authored-function.blend',
            names=[resource['name']],expected_sha256=library['sha256'],lease_id=lease)
        actual=appended['roots'][0]['name']
        await call('assign_material',action='create_node',**context,node='AuthoredC',node_type='ShaderNodeGroup',
            node_settings={'node_tree':actual},lease_id=lease)
        await bake('AuthoredC','authored-c')
        snapshot=await inspect()
        await call('asset_io',action='save',path='authored-consumer.blend',lease_id=lease)
        evidence=json.loads((root/'author-bakes.json').read_text())
        for name,value in [('authored-a',-.1),('authored-b',1.25),('authored-c',-.1)]:
            assert max(abs(evidence[name][key]-value) for key in ['min','max'])<1e-6,evidence
        await call('asset_io',action='open',path='authored-consumer.blend',lease_id=lease)
        assert await inspect()==snapshot
        assert (await call('asset_library',action='inspect',kind='node_groups',path='authored-function.blend'))['sha256']==library['sha256']
        await call('session_control',action='release',lease_id=lease);await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'author-evidence.json').write_text(json.dumps(
                {'bakes':evidence,'interface':interface,'appended_group':actual},indent=2)+'\n')
        return {'shader_function_authoring':'passed','scoped_profile':scoped,'bakes':evidence,
            'typed_interface_and_reuse':'passed','definition_rollback':'passed','save_reopen':'passed'}


if __name__=='__main__':main(exercise,Path(__file__).with_name('shader_group_author_fixture.py'))
