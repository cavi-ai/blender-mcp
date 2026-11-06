"""Named UV sampling and normal tangents through real MCP and native Blender."""

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main
from PIL import Image


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            result = await client.call_tool(tool, args)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='uv-layer-fixture',
                            expected_project=state['project_id']))['lease_id']

        async def render(name):
            await call('scene_edit', action='render', lease_id=lease, render={
                'path': name + '.png', 'camera': 'UV Camera', 'width': 64, 'height': 64,
                'engine': 'cycles', 'device': 'CPU', 'samples': 1, 'denoise': False, 'view_transform': 'Standard'})
            with Image.open(root / (name + '.png')) as image:
                return image.convert('RGB').getpixel((32, 32))

        baseline = await render('baseline')
        assert baseline[0] > baseline[2] + 60, baseline
        before = await call('assign_material', action='inspect', material_name='SharedFinish')
        rejected = await client.call_tool('assign_material', {'names': ['Subject'],
            'material_name': 'SharedFinish', 'update_existing': True, 'uv_layer': 'Atlas', 'lease_id': lease})
        assert rejected.is_error, rejected
        after = await call('assign_material', action='inspect', material_name='SharedFinish')
        assert before['nodes'] == after['nodes']
        await call('assign_material', names=['Subject'], material_name='AtlasFinish',
            base_color_texture='color.png', normal_texture='normal.png', uv_layer='Atlas', lease_id=lease)
        nodes = (await call('assign_material', action='inspect', material_name='AtlasFinish'))['nodes']
        assert {node['type']: node['uv_map'] for node in nodes if node['type'] in ('UVMAP', 'NORMAL_MAP')} == {
            'UVMAP': 'Atlas', 'NORMAL_MAP': 'Atlas'}, nodes
        atlas = await render('atlas')
        assert atlas[2] > atlas[0] + 60, atlas
        await call('assign_material', names=['Subject'], material_name='AtlasFinish',
            update_existing=True, uv_layer='', lease_id=lease)
        restored = await render('render-active')
        assert restored[0] > restored[2] + 60, restored
        await call('asset_io', action='save', path='material-uv.blend', lease_id=lease)
        await call('session_control', action='release', lease_id=lease)
        return {'baseline_pixel': baseline, 'atlas_pixel': atlas, 'render_active_pixel': restored,
                'named_texture_uv': True, 'named_normal_tangents': True,
                'shared_owner_rejection_preserves_graph': True, 'mesh_render_uv_preserved': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('material_uv_fixture.py'))
