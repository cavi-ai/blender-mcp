"""Real MCP read-only UV preflight identifies a missing tile and verifies its repair."""

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m','cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()
        async def call(tool, **arguments):
            reply = await client.call_tool(tool, arguments)
            assert not reply.is_error, reply
            return reply.structured_content
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='texture-author',
            expected_project=state['project_id']))['lease_id']
        async def bind(numbers):
            result = await call('assign_material', action='set_image', material_name='ArtistFinish',
                group_path=['Finish Controls','Inner Layer'], node='Pattern', lease_id=lease,
                image={'path':'glaze.<UDIM>.png','tiles':numbers,'color_space':'Non-Color'})
            return result['nodes'][0]['image']['name']
        image = await bind([1001,1002,1011])
        options = {'names':['TileGrid','OtherSurface'], 'udim_image':image, 'material':'ArtistFinish'}
        before = await call('scene_info', limit=1)
        missing = await call('inspect_uv_layout', **options)
        after = await call('scene_info', limit=1)
        assert before['source_state'] == after['source_state'] and before['objects'] == after['objects']
        assert missing['scope'] == 'source_uv_udim_coverage'
        assert missing['complete'] and not missing['coverage']['passed']
        assert missing['coverage']['missing_tiles'] == [1012]
        assert [o['triangles'] for o in missing['objects']] == [2,0]
        assert all(e['object'] == 'TileGrid' and e['face'] == 0 for e in missing['coverage']['examples'])
        incomplete = await call('inspect_uv_layout', **options, comparison_budget=1)
        assert not incomplete['complete'] and not incomplete['coverage']['passed']
        assert incomplete['coverage']['unused_tiles'] is None
        collapsed = await call('inspect_uv_layout', **options, uv_layer='CollapsedUV')
        assert not collapsed['coverage']['passed'] and collapsed['coverage']['degenerate_triangles'] == 2
        unavailable = await call('inspect_uv_layout', **(options | {'udim_image':'UnavailableTiles'}))
        assert 1012 in unavailable['coverage']['unavailable_tiles'] and not unavailable['coverage']['passed']
        image = await bind([1001,1002,1011,1012])
        repaired = await call('inspect_uv_layout', **(options | {'udim_image':image}))
        assert repaired['complete'] and repaired['coverage']['passed']
        assert repaired['coverage']['required_tiles'] == [1001,1002,1011,1012]
        assert repaired['coverage']['missing_tiles'] == []
        assert all(o['uv_layer_index'] == 0 for o in repaired['objects'])
        assert (await call('session_control', action='inspect'))['owner'] == 'texture-author'
        assert 'shader vector transforms and projections' in repaired['not_checked']
        wrong = await client.call_tool('inspect_uv_layout', {'names':['TileGrid'],'udim_image':'missing'})
        assert wrong.is_error
        catalog = await client.list_tools()
        assert len(catalog.tools) == 20
        assert next(t for t in catalog.tools if t.name == 'inspect_uv_layout').annotations.read_only_hint
        return {'mcp_version':initialized.server_info.version,'tool_count':len(catalog.tools),
            'missing_tile':missing['coverage']['missing_tiles'], 'repaired_tiles':repaired['coverage']['required_tiles'],
            'affected_faces':missing['coverage']['examples'],'object_material_override_filtered':True,
            'incomplete_and_unavailable_never_pass':True,'source_uv0_and_named_layer_checked':True,
            'inspection_lease_free_while_author_owned':True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('udim_coverage_fixture.py'))
