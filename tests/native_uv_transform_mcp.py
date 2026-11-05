"""Real MCP face repair, source coverage and matched native Cycles CPU renders."""
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main
from PIL import Image


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m','cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()
        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            return result.structured_content
        edit = {'action':'uv_transform','name':'TileGrid','uv_layer':'UVMap',
                'uv_transform':{'faces':[0],'offset':[-1,-1]}}
        assert (await client.call_tool('mesh_edit', edit)).is_error
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='uv-author',
            expected_project=state['project_id']))['lease_id']
        bound = await call('assign_material', action='set_image', material_name='ArtistFinish',
            group_path=['Finish Controls','Inner Layer'], node='Pattern', lease_id=lease,
            image={'path':'glaze.<UDIM>.png','tiles':[1001,1002,1011],'color_space':'Non-Color'})
        image = bound['nodes'][0]['image']['name']
        options = {'names':['TileGrid'], 'udim_image':image, 'uv_layer':'UVMap'}
        before = await call('inspect_uv_layout', **options)
        assert before['coverage']['missing_tiles'] == [1012]
        assert {e['face'] for e in before['coverage']['examples']} == {0}
        async def render(name):
            await call('scene_edit', action='render', lease_id=lease, render={
                'path':name+'.png', 'camera':'TileCamera','engine':'cycles','device':'CPU',
                'width':64,'height':64,'samples':1,'denoise':False,'view_transform':'Standard'})
            path = root/(name+'.png')
            assert path.read_bytes()[24] == 16, 'Render did not preserve requested PNG16 precision'
            with Image.open(path) as capture:
                return capture.convert('RGB').getpixel((16,32)), capture.convert('RGB').getpixel((48,32))
        missing, unchanged_before = await render('missing')
        assert missing[0] > 180 and missing[2] > 180 and missing[1] < 50, missing
        fixed = await call('mesh_edit', **edit, lease_id=lease)
        assert fixed['uv_transform']['faces'] == [0] and fixed['uv_transform']['loops'] == 4
        after = await call('inspect_uv_layout', **options)
        assert after['complete'] and after['coverage']['passed']
        assert after['coverage']['required_tiles'] == [1001]
        repaired, unchanged_after = await render('repaired')
        assert repaired[0] > 180 and repaired[1] < 80 and repaired[2] < 80, repaired
        assert unchanged_before == unchanged_after
        rejected = await client.call_tool('mesh_edit', {**edit,'lease_id':lease,
            'uv_transform':{'faces':[999],'offset':[1,0]}})
        assert rejected.is_error
        assert (await call('inspect_uv_layout', **options))['coverage'] == after['coverage']
        # UV0 is explicit policy even when another layer is active/render-active.
        default = await call('mesh_edit', action='uv_transform', name='TileGrid', lease_id=lease,
            uv_transform={'faces':[1],'offset':[0,0]})
        assert default['uv_layer'] == 'UVMap'
        assert (await call('session_control', action='inspect'))['owner'] == 'uv-author'
        await call('session_control', action='release', lease_id=lease)
        catalog = await client.list_tools()
        assert len(catalog.tools) == 20
        return {'mcp_version':initialized.server_info.version,'tool_count':len(catalog.tools),
            'missing_tiles':before['coverage']['missing_tiles'],'repaired_required_tiles':after['coverage']['required_tiles'],
            'missing_pixel':missing,'repaired_pixel':repaired,'unselected_face_pixel_unchanged':True,
            'native_cycles_cpu_png_bits':16,'lease_and_rejection_checked':True,'default_uv0_checked':True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('uv_transform_fixture.py'))
