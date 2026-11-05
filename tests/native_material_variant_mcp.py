"""Real MCP material branching and matched native material-control renders."""
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main
from PIL import Image


async def exercise(root, env):
    params=StdioServerParameters(command=sys.executable,args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized=await client.initialize()
        async def call(tool, **arguments):
            result=await client.call_tool(tool,arguments)
            assert not result.is_error,result
            return result.structured_content
        request={'action':'make_unique','names':['TileGrid'],'material_name':'VariantFinish'}
        assert (await client.call_tool('assign_material',request)).is_error
        state=await call('session_control',action='inspect')
        lease=(await call('session_control',action='claim',owner='finish-author',
            expected_project=state['project_id']))['lease_id']
        await call('assign_material',action='set_image',material_name='ArtistFinish',
            group_path=['Finish Controls','Inner Layer'],node='Pattern',lease_id=lease,
            image={'path':'glaze.<UDIM>.png','tiles':[1001,1002,1011,1012],'color_space':'Non-Color'})
        async def render(name):
            await call('scene_edit',action='render',lease_id=lease,render={
                'path':name+'.png','camera':'TileCamera','width':64,'height':64,
                'engine':'cycles','device':'CPU','samples':1,'denoise':False,'view_transform':'Standard'})
            path=root/(name+'.png')
            assert path.read_bytes()[24]==16
            with Image.open(path) as capture:
                rgb=capture.convert('RGB')
                return rgb.getpixel((16,32)),rgb.getpixel((48,32))
        before=await call('scene_info',name='TileGrid')
        baseline,peer_before=await render('baseline')
        result=await call('assign_material',**request,lease_id=lease)
        assert result['material_copy']['source']=='ArtistFinish'
        assert result['material_copy']['node_group_count']==2
        assert result['bindings'][0]['link_mode']=='OBJECT' and result['bindings'][0]['mesh_users']==3
        copied,peer_copied=await render('copied')
        assert copied==baseline and peer_copied==peer_before
        path=['Finish Controls','Inner Layer']
        source=await call('assign_material',action='inspect',material_name='ArtistFinish',group_path=path,node='Variant Gain')
        await call('assign_material',action='set_inputs',material_name='VariantFinish',group_path=path,
            node='Variant Gain',outputs={'Value':.25},lease_id=lease)
        changed,peer_after=await render('changed')
        assert max(changed)<max(baseline)-40,(baseline,changed)
        assert peer_after==peer_before
        source_after=await call('assign_material',action='inspect',material_name='ArtistFinish',group_path=path,node='Variant Gain')
        assert source_after['nodes']==source['nodes']
        after=await call('scene_info',name='TileGrid')
        assert before['location']==after['location'] and before['vertices']==after['vertices']
        assert (await client.call_tool('assign_material',{**request,'lease_id':lease})).is_error
        await call('asset_io',action='save',path='material-variant.blend',lease_id=lease)
        await call('session_control',action='release',lease_id=lease)
        assert len((await client.list_tools()).tools)==20
        return {'mcp_version':initialized.server_info.version,'tool_count':20,
            'copy_matches_original_render':True,'baseline_pixel':baseline,'variant_pixel':changed,
            'peer_pixel_unchanged':True,'source_graph_unchanged':True,'geometry_shared':True,
            'native_cycles_cpu_png_bits':16,'lease_and_collision_checked':True}


if __name__=='__main__':
    main(exercise,Path(__file__).with_name('material_variant_fixture.py'))
