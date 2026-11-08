"""Import and instance native shader functions through scoped MCP and float bakes."""
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
        before=json.loads((root/'group-audit.json').read_text())
        context={'material_name':'ArtistFinish','group_path':['Finish']}
        async def inspect(**options):return await call('assign_material',action='inspect',**{**context,**options})
        original=await inspect()
        types=await call('assign_material',action='node_types',node_type='ShaderNodeGroup',**context)
        assert types['node_types'][0]['resource_schema']['node_tree']['parameter']=='node_settings.node_tree'
        catalog=await call('asset_library',action='inspect',kind='node_groups',path='finishes.blend')
        assert {'StudioFinish','GeometrySentinel'}<=set(catalog['names'])
        assert (await client.call_tool('assign_material',{'action':'create_node',**context,'node':'Unowned',
            'node_type':'ShaderNodeGroup','node_settings':{'node_tree':'StudioFinish'}})).is_error
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='shader-group-native',expected_project=state['project_id']))['lease_id']
        for group in ['MissingFinish','GeometrySentinel','SurfaceGraph','RecursiveBridge',False,None]:
            result=await client.call_tool('assign_material',{'action':'create_node',**context,'node':'Rejected',
                'node_type':'ShaderNodeGroup','node_settings':{'node_tree':group},'lease_id':lease})
            assert result.is_error and result.structured_content['error']['outcome']=='rejected',result
            assert await inspect()==original
        for kind,settings in [('ShaderNodeMath',{'node_tree':'StudioFinish'}),
            ('ShaderNodeGroup',{'node_tree':'StudioFinish','missing':True})]:
            result=await client.call_tool('assign_material',{'action':'create_node',**context,'node':'Rejected',
                'node_type':kind,'node_settings':settings,'lease_id':lease})
            assert result.is_error and await inspect()==original
        assert not (await call('scene_info',limit=1))['source_state']['dirty']
        imported=await call('asset_library',action='append',kind='node_groups',path='finishes.blend',
            names=['StudioFinish'],expected_sha256=catalog['sha256'],lease_id=lease)
        group=imported['roots'][0]['name'];assert group!='StudioFinish'
        inputs,outputs={},{}
        for name,value in [('FinishA',-.2),('FinishB',2.5)]:
            created=await call('assign_material',action='create_node',**context,node=name,node_type='ShaderNodeGroup',
                node_settings={'node_tree':group},lease_id=lease)
            assert created['nodes'][0]['group']==group
            assert created['created_node']['resources']['node_tree']['name']==group
            if name=='FinishA':assert created['managed_materials_detached']==['ManagedA','ManagedB']
            inputs[name]=next(s['identifier'] for s in created['nodes'][0]['inputs'] if s['name']=='Signal')
            outputs[name]=next(s['identifier'] for s in created['nodes'][0]['outputs'] if s['name']=='Result')
            await call('assign_material',action='set_inputs',**context,node=name,inputs={inputs[name]:value},lease_id=lease)
        surface=await inspect(node='Surface')
        strength=next(s['identifier'] for s in surface['nodes'][0]['inputs'] if s['name']=='Strength')
        await call('assign_material',action='connect',**context,node='Surface',
            inputs={strength:{'node':'FinishB','socket':outputs['FinishB']}},lease_id=lease)
        async def bake(node,path):
            result=await call('bake',map='shader',name='RampSurface',path=path+'.exr',
                source={'material':'ArtistFinish','group_path':['Finish'],
                    'node':'Surface' if node=='FinishB' else node,'socket':strength if node=='FinishB' else outputs[node],
                    'direction':'INPUT' if node=='FinishB' else 'OUTPUT','role':'data'},
                resolution=64,samples=1,margin=0,bit_depth=32,lease_id=lease)
            assert result['bit_depth']==32
        await bake('FinishA','group-a');await bake('FinishB','group-b')
        nested=await inspect(group_path=['Finish','FinishA'],node='StudioGain')
        factor=nested['nodes'][0]['inputs'][1]['identifier']
        await call('assign_material',action='set_inputs',material_name='ArtistFinish',group_path=['Finish','FinishA'],
            node='StudioGain',inputs={factor:.5},lease_id=lease)
        for node,expected in [('FinishA',-.2),('FinishB',2.5)]:
            actual=(await inspect(node=node))['nodes'][0]['inputs'][0]['value']
            assert abs(actual-expected)<1e-6
        await bake('FinishA','group-a-shared');await bake('FinishB','group-b-shared')
        snapshot=await inspect()
        await call('asset_io',action='save',path='group-instances.blend',lease_id=lease)
        evidence=json.loads((root/'group-audit.json').read_text())
        assert evidence['collision_gain']==before['collision_gain']
        for name,value in [('group-a',-.05),('group-b',.625),('group-a-shared',-.1),('group-b-shared',1.25)]:
            assert max(abs(evidence['bakes'][name][key]-value) for key in ['min','max'])<1e-6,evidence
        assert (await call('asset_library',action='inspect',kind='node_groups',path='finishes.blend'))['sha256']==catalog['sha256']
        await call('asset_io',action='open',path='group-instances.blend',lease_id=lease)
        assert await inspect()==snapshot
        await call('session_control',action='release',lease_id=lease);await verify_source_identity(env)
        if os.environ.get('CAVI_NATIVE_EVIDENCE'):
            (Path(os.environ['CAVI_NATIVE_EVIDENCE'])/'group-evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
        return {'shader_group_instances':'passed','scoped_profile':scoped,'imported_group':group,'bakes':evidence,
            'connected_input_bakes':'passed',
            'recursion_and_type_guards':'passed','creation_rollback':'passed','library_unchanged':'passed','save_reopen':'passed'}


if __name__=='__main__':main(exercise,Path(__file__).with_name('shader_group_fixture.py'))
