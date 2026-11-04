"""Real MCP control edits through shared and independent native kit instances."""

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
        lease = (await call('session_control', action='claim', owner='instance-controls-check',
            expected_project=state['project_id']))['lease_id']
        source = await call('asset_library', action='inspect', path='kit.blend')

        async def append():
            return await call('asset_library', action='append', path='kit.blend', names=['ProceduralKit'],
                expected_sha256=source['sha256'], instance_collections=True, lease_id=lease)

        shared, independent = await append(), await append()
        a, c = shared['instances'][0]['name'], independent['instances'][0]['name']
        await call('object_edit', action='duplicate', name=a, new_name='Kit_B', linked=True, lease_id=lease)
        b = 'Kit_B'
        await call('object_edit', action='transform', name=b, location=[4, 0, 0], lease_id=lease)

        def member(loaded, source_name):
            return next(i['name'] for i in loaded['items'] if i['id_type'] == 'OBJECT' and i['source_name'] == source_name)

        fence, inner = member(shared, 'Fence'), member(shared, 'OtherFence')
        other = member(independent, 'Fence')
        inventory = await call('scene_info', name=a, definition=True, limit=1)
        assert inventory['total'] == 3 and inventory['scene_instances'] == sorted([a, b]), inventory
        pages = [await call('scene_info', name=a, definition=True, offset=i, limit=1) for i in range(3)]
        assert {row['name'] for page in pages for row in page['objects']} == {fence, inner, member(shared, 'NestedModule')}
        before = await call('scene_info', limit=1000)

        async def controls(name, instance):
            return await call('geometry_nodes', action='inspect', name=name, instance=instance)

        original = await controls(fence, a)
        count = next(s['identifier'] for s in original['modifiers'][0]['inputs'] if s['name'] == 'Count')

        async def count_value(name, instance):
            return next(s['value'] for s in (await controls(name, instance))['modifiers'][0]['inputs'] if s['name'] == 'Count')

        baseline = await call('asset_io', action='export', path='baseline.glb', names=[a, b], assembly=True, lease_id=lease)
        assert baseline['triangles'] == 144, baseline
        for name, amount in [(fence, 5), (inner, 4)]:
            changed = await call('geometry_nodes', action='set_inputs', name=name, instance=a,
                modifier='Generator', inputs={count: amount}, lease_id=lease)
            assert changed['instance'] == a and changed['definition'] == inventory['instance_collection'], changed
            assert await count_value(name, b) == amount
        assert await count_value(other, c) == 3
        assert (await controls(fence, b))['modifiers'][0]['node_group'] == original['modifiers'][0]['node_group']
        for name, instance, values in [('Cube', a, {count: 7}), (other, a, {count: 7}),
                                      (fence, 'Cube', {count: 7}), (fence, a, {count: 5.5})]:
            result = await client.call_tool('geometry_nodes', {'action': 'set_inputs', 'name': name,
                'instance': instance, 'modifier': 'Generator', 'inputs': values, 'lease_id': lease})
            assert result.is_error, result
            assert await count_value(fence, a) == 5 and await count_value(inner, a) == 4
        assert (await call('scene_info', limit=1000))['objects'] == before['objects']
        edited = await call('asset_io', action='export', path='edited.glb', names=[a, b], assembly=True, lease_id=lease)
        separate = await call('asset_io', action='export', path='independent.glb', names=[c], assembly=True, lease_id=lease)
        assert edited['triangles'] == 216 and separate['triangles'] == 72, (edited, separate)
        imported = await call('asset_io', action='import', path='edited.glb', name='CheckedKit', lease_id=lease)
        assert imported['imported_triangles'] == 216, imported
        assert (await call('asset_library', action='inspect', path='kit.blend'))['sha256'] == source['sha256']
        await call('asset_io', action='save', path='consumer.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'shared_instances': 2,
                'nested_control_values': [5, 4], 'independent_count': 3,
                'baseline_triangles': baseline['triangles'], 'edited_triangles': edited['triangles'],
                'independent_triangles': separate['triangles'], 'reimported_triangles': imported['imported_triangles'],
                'paginated_definition_inspection': True, 'invalid_edits_preserved_inputs': True,
                'source_file_unchanged': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('instance_controls_fixture.py'))
