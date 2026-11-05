"""Owned UV promotion and assembly export through real MCP stdio and Blender."""
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root,env):
    params=StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(params) as streams,ClientSession(*streams) as client:
        await client.initialize()
        async def call(tool,**args):
            result=await client.call_tool(tool,args)
            assert not result.is_error,result
            return result.structured_content
        request={'action':'export','path':'hero.fbx','names':['Hero'],'uv_layer':'Atlas'}
        assert (await client.call_tool('asset_io',request)).is_error
        assert not (root/'hero.fbx').exists()
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='uv-export',
                         expected_project=state['project_id']))['lease_id']
        before=await call('scene_info',name='Hero')
        original=await call('inspect_uv_layout',names=['Hero'],texture_resolution=[64,64],padding_pixels=0)
        assert not original['unique_tile_ready']
        result=await call('asset_io',**request,lease_id=lease)
        assert result['uv_maps'][0]['source_index']==1 and result['uv_maps'][0]['export_index']==0
        imported=await call('asset_io',action='import',path='hero.fbx',name='Imported',lease_id=lease)
        name=next(o['name'] if isinstance(o,dict) else o for o in imported['objects'])
        atlas=await call('inspect_uv_layout',names=[name],texture_resolution=[64,64],padding_pixels=0)
        assert atlas['complete'] and atlas['unique_tile_ready']
        assert atlas['objects'][0]['uv_layer_index']==0
        assembly=await call('asset_io',action='export',path='kit.glb',names=['Kit'],assembly=True,
                            uv_layer='Atlas',lease_id=lease)
        assert assembly['uv_maps'] and all(row['export_index']==0 for row in assembly['uv_maps'])
        assert assembly['triangles']==2
        after=await call('scene_info',name='Hero')
        assert all(before.get(k)==after.get(k) for k in ['vertices','materials','shape_key_names','location','scale'])
        animated=await call('asset_io',action='export',path='skin.fbx',names=['Skin'],
            animations=True,baked_animation=True,uv_layer='Atlas',lease_id=lease)
        assert animated['uv_maps'][0]['export_index']==0 and animated['skinned_meshes']==['Skin']
        loaded=await call('asset_io',action='import',path='skin.fbx',name='Animation',lease_id=lease)
        assert len(loaded['armatures'])==len(loaded['skinned_meshes'])==1
        compared=await call('compare_rig_motion',source='Rig',candidate=loaded['armatures'][0],
            meshes=[{'source':'Skin','candidate':loaded['skinned_meshes'][0]}],
            start_frame=1,end_frame=3,samples=2,max_error_m=.00001,space='world',vertex_match='point_set',
            candidate_frame_offset=loaded['animations'][0]['frame_range'][0]-1)
        assert compared['passed'],compared
        original_after=await call('inspect_uv_layout',names=['Hero'],texture_resolution=[64,64],padding_pixels=0)
        assert original_after['objects']==original['objects'] and not original_after['unique_tile_ready']
        await call('session_control',action='release',lease_id=lease)
        return {'native_uv_export_mcp':'passed','uv0_atlas_reimport':'passed',
                'evaluated_collection_atlas':'passed','source_shader_uv_and_actor_preserved':True,
                'lease_required':True,'fbx_bytes':result['bytes'],'assembly_bytes':assembly['bytes'],
                'animated_skin_max_error_m':compared['max_error_m']}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('export_uv_sdk_fixture.py'))
