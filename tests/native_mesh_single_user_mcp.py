"""Real MCP ownership change unlocks isolated UV and expression authoring."""
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params=StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized=await client.initialize()
        async def call(tool, **arguments):
            result=await client.call_tool(tool,arguments)
            assert not result.is_error,result
            return result.structured_content
        assert (await client.call_tool('object_edit',{'action':'make_single_user','name':'TileGrid'})).is_error
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='variant-author',
            expected_project=state['project_id']))['lease_id']
        before=await call('scene_info',name='TileGrid')
        count=(await call('scene_info',limit=1))['total']
        # Existing scene and object-transform dispatch must still work after UV routing.
        await call('object_edit',action='transform',name='TileGrid',location=before['location'],lease_id=lease)
        blocked=await client.call_tool('mesh_edit',{'action':'uv_transform','name':'TileGrid',
            'uv_layer':'UVMap','uv_transform':{'faces':[0],'offset':[-1,-1]},'lease_id':lease})
        assert blocked.is_error
        result=await call('object_edit',action='make_single_user',name='TileGrid',lease_id=lease)
        receipt=result['mesh_copy']
        assert receipt['copied'] and receipt['mesh']!=receipt['source'] and receipt['users']==1
        after=await call('scene_info',name='TileGrid')
        for field in ['name','location','rotation_degrees','scale','dimensions','parent','collections','modifiers']:
            assert before[field]==after[field],field
        assert (await call('scene_info',limit=1))['total']==count
        assert not (await call('object_edit',action='make_single_user',name='TileGrid',lease_id=lease))['mesh_copy']['copied']
        bound=await call('assign_material',action='set_image',material_name='ArtistFinish',
            group_path=['Finish Controls','Inner Layer'],node='Pattern',lease_id=lease,
            image={'path':'glaze.<UDIM>.png','tiles':[1001,1002,1011,1012],'color_space':'Non-Color'})
        image=bound['nodes'][0]['image']['name']
        async def coverage(name):
            return (await call('inspect_uv_layout',names=[name],udim_image=image,uv_layer='UVMap'))['coverage']
        peer_before=await coverage('LinkedPeer')
        await call('mesh_edit',action='uv_transform',name='TileGrid',uv_layer='UVMap',
            uv_transform={'faces':[0],'offset':[-1,-1]},lease_id=lease)
        target=await coverage('TileGrid')
        assert target['passed'] and target['required_tiles']==[1001]
        assert await coverage('LinkedPeer')==peer_before and peer_before['required_tiles']==[1001,1012]
        await call('object_edit',action='shape_key_add',name='TileGrid',new_name='VariantSmile',lease_id=lease)
        assert 'VariantSmile' in (await call('scene_info',name='TileGrid'))['shape_key_names']
        assert 'VariantSmile' not in (await call('scene_info',name='LinkedPeer'))['shape_key_names']
        await call('asset_io',action='save',path='variant.blend',lease_id=lease)
        await call('session_control',action='release',lease_id=lease)
        assert len((await client.list_tools()).tools)==20
        return {'mcp_version':initialized.server_info.version,'tool_count':20,'receipt':receipt,
            'object_identity_and_transforms_retained':True,'peer_uv_and_expressions_independent':True,
            'scene_and_transform_dispatch_checked':True,'lease_and_no_op_checked':True,
            'variant_saved':(root/'variant.blend').exists()}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('mesh_single_user_fixture.py'))
