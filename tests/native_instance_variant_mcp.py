"""Fork the current edited kit through MCP, then change only the selected placement."""

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
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='instance-variant-check',
            expected_project=state['project_id']))['lease_id']
        source = await call('asset_library', action='inspect', path='variant-kit.blend')
        loaded = await call('asset_library', action='append', path='variant-kit.blend', names=['EditableKit'],
            expected_sha256=source['sha256'], instance_collections=True, lease_id=lease)
        a = loaded['instances'][0]['name']

        def member(items, name):
            return next(i['name'] for i in items if i['id_type'] == 'OBJECT' and i['source_name'] == name)

        initial = await call('scene_info', name=a, definition=True)
        fence = next(v['name'] for v in initial['objects'] if any(m['type'] == 'NODES' for m in v['modifiers']) and v['name'] != 'InnerFence')
        inner = member(loaded['items'], 'InnerFence')

        async def controls(name, instance):
            return await call('geometry_nodes', action='inspect', name=name, instance=instance)

        original = await controls(fence, a)
        count = next(s['identifier'] for s in original['modifiers'][0]['inputs'] if s['name'] == 'Count')

        async def set_count(name, instance, amount):
            return await call('geometry_nodes', action='set_inputs', name=name, instance=instance,
                modifier='Generator', inputs={count: amount}, lease_id=lease)

        async def get_count(name, instance):
            return next(s['value'] for s in (await controls(name, instance))['modifiers'][0]['inputs'] if s['name'] == 'Count')

        await set_count(fence, a, 5)
        await set_count(inner, a, 4)
        await call('object_edit', action='duplicate', name=a, new_name='Kit_B', linked=True, lease_id=lease)
        await call('object_edit', action='transform', name='Kit_B', location=[4, 1, 0],
            rotation_degrees=[15, 0, 90], scale=[-1.2, .8, 1.1], lease_id=lease)
        before = await call('scene_info', name='Kit_B')
        fork = await call('object_edit', action='make_unique', name='Kit_B', new_name='TunedKit', lease_id=lease)
        after = await call('scene_info', name='Kit_B')
        assert before == after
        assert fork['source_collection'] == initial['instance_collection'] and fork['instance_collection'] == 'TunedKit', fork
        fork_fence, fork_inner = member(fork['items'], fence), member(fork['items'], inner)
        assert await get_count(fork_fence, 'Kit_B') == 5 and await get_count(fork_inner, 'Kit_B') == 4
        assert (await controls(fork_fence, 'Kit_B'))['modifiers'][0]['node_group'] != original['modifiers'][0]['node_group']
        await set_count(fork_fence, 'Kit_B', 7)
        assert await get_count(fence, a) == 5 and await get_count(inner, a) == 4
        assert (await call('scene_info', name=a, definition=True))['scene_instances'] == [a]
        assert (await call('scene_info', name='Kit_B', definition=True))['scene_instances'] == ['Kit_B']
        bad = await client.call_tool('object_edit', {'action': 'make_unique', 'name': a, 'new_name': 'TunedKit', 'lease_id': lease})
        assert bad.is_error
        assert (await call('scene_info', name=a, definition=True))['instance_collection'] == initial['instance_collection']
        for name, expected, path in [(a, 120, 'shared.glb'), ('Kit_B', 144, 'variant.glb')]:
            result = await call('asset_io', action='export', path=path, names=[name], assembly=True, lease_id=lease)
            assert result['triangles'] == expected, result
            imported = await call('asset_io', action='import', path=path, name='Checked'+path.split('.')[0], lease_id=lease)
            assert imported['imported_triangles'] == expected, imported
        assert (await call('asset_library', action='inspect', path='variant-kit.blend'))['sha256'] == source['sha256']
        await call('asset_io', action='save', path='consumer.blend', lease_id=lease)
        assert not list(root.glob('.cavi-variant-*'))
        return {'mcp_version': initialized.server_info.version, 'fork_retained_current_controls': [5, 4],
            'source_count_after_variant_edit': 5, 'variant_count': 7, 'placement_transform_preserved': True,
            'independent_node_group': True, 'shared_triangles': 120, 'variant_triangles': 144,
            'native_glb_reimports': True, 'source_file_unchanged': True, 'temporary_snapshot_removed': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('instance_variant_fixture.py'))
