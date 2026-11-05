"""Real MCP texture replacement and Value/RGB defaults preserve native authoring."""

import hashlib
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()
        async def call(tool, **arguments):
            reply = await client.call_tool(tool, arguments)
            assert not reply.is_error, reply
            return reply.structured_content
        path = ['Finish Controls', 'Inner Layer']
        common = {'material_name': 'ArtistFinish', 'group_path': path}
        async def inspect(node):
            return await call('assign_material', action='inspect', node=node, **common)
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='texture-check',
            expected_project=state['project_id']))['lease_id']
        sibling = await inspect('Other Pattern')
        old = await inspect('Pattern')
        before = await inspect('Glaze Weight')
        value_id = before['nodes'][0]['outputs'][0]['identifier']
        value = await call('assign_material', action='set_inputs', node='Glaze Weight',
            outputs={value_id: .6}, lease_id=lease, **common)
        assert value['changed_outputs'] == [value_id] and value['links'] == before['links']
        tint = await inspect('Glow Tint')
        color_id = tint['nodes'][0]['outputs'][0]['identifier']
        color = await call('assign_material', action='set_inputs', node='Glow Tint',
            outputs={color_id: [.1, .2, .4, 1.]}, lease_id=lease, **common)
        assert color['links'] == tint['links']
        sources = {}
        for filename in ['finish.png', 'finish.tiff', 'finish.exr']:
            result = await call('assign_material', action='set_image', node='Pattern',
                image={'path': filename, 'color_space': 'Non-Color', 'alpha_mode': 'CHANNEL_PACKED'},
                lease_id=lease, **common)
            assert result['changed_image'] and result['links'] == old['links']
            assert result['image_source']['sha256'] == hashlib.sha256((root/filename).read_bytes()).hexdigest()
            image = result['nodes'][0]['image']
            assert image['packed'] and image['color_space'] == 'Non-Color' and image['alpha_mode'] == 'CHANNEL_PACKED'
            sources[filename] = result['image_source']['sha256']
            noop = await call('assign_material', action='set_image', node='Pattern',
                image={'path': filename, 'color_space': 'Non-Color', 'alpha_mode': 'CHANNEL_PACKED'},
                lease_id=lease, **common)
            assert not noop['changed_image']
        assert await inspect('Other Pattern') == sibling
        baseline = await inspect('Pattern')
        for image in [{'path': 'finish.png', 'color_space': 'not-an-OCIO-space'},
                      {'path': '../outside.png', 'color_space': 'Non-Color'}]:
            rejected = await client.call_tool('assign_material', {'action': 'set_image',
                'node': 'Pattern', 'image': image, 'lease_id': lease, **common})
            assert rejected.is_error
            assert await inspect('Pattern') == baseline
        missing_lease = await client.call_tool('assign_material', {'action': 'set_image',
            'node': 'Pattern', 'image': {'path': 'finish.png', 'color_space': 'Non-Color'}, **common})
        assert missing_lease.is_error
        await call('asset_io', action='save', path='authored-textures.blend', lease_id=lease)
        catalog = await client.list_tools()
        assert len(catalog.tools) == 20
        return {'mcp_version': initialized.server_info.version, 'tool_count': len(catalog.tools),
            'value_and_rgb_outputs': True, 'links_preserved': True,
            'other_image_binding_unchanged': True, 'no_op_reuses_packed_image': True,
            'invalid_and_unowned_edits_rejected': True, 'source_sha256': sources}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('shader_texture_fixture.py'))
