"""Real MCP native shader defaults, nested discovery and managed ownership handoff."""

import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()
        catalog = await client.list_tools()
        assert len(catalog.tools) == 20

        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            return result.structured_content

        async def inspect(material='ArtistFinish', **options):
            return await call('assign_material', action='inspect', material_name=material, **options)

        initial = await inspect()
        assert initial['total'] == 2 and not initial['managed_configuration']
        assert len((await inspect(limit=1, offset=1))['nodes']) == 1
        group = next(n for n in initial['nodes'] if n['type'] == 'GROUP')
        roughness = next(i['identifier'] for i in group['inputs'] if i['name'] == 'Roughness')
        tint = next(i['identifier'] for i in group['inputs'] if i['name'] == 'Tint')
        path = ['Finish Controls', 'Inner Layer']
        nested = await inspect(group_path=path, node='Hero Surface')
        hero = nested['nodes'][0]
        coat = next(i['identifier'] for i in hero['inputs'] if i['name'] == 'Coat Weight')
        linked = next(i['identifier'] for i in hero['inputs'] if i['name'] == 'Roughness')
        assert next(i['linked'] for i in hero['inputs'] if i['identifier'] == linked)
        assert set(nested['affected_materials']) == {'ArtistFinish', 'OtherFinish', 'ManagedA', 'ManagedB'}
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='shader-input-check',
            expected_project=state['project_id']))['lease_id']

        async def edit(**options):
            return await call('assign_material', action='set_inputs', material_name='ArtistFinish', lease_id=lease, **options)

        await edit(node='Finish Controls', inputs={roughness: .25, tint: [.1, .2, .3, 1.]})
        other = (await inspect('OtherFinish', node='Finish Controls'))['nodes'][0]
        assert abs(next(i['value'] for i in other['inputs'] if i['identifier'] == roughness)-.65) < 1e-6
        changed = await edit(group_path=path, node='Hero Surface', inputs={coat: .4, linked: .33})
        assert changed['links'] == nested['links']
        assert changed['managed_materials_detached'] == ['ManagedA', 'ManagedB']
        assert next(i['linked'] for i in changed['nodes'][0]['inputs'] if i['identifier'] == linked)
        for name in ['ManagedA', 'ManagedB']:
            info = await inspect(name)
            assert not info['managed_configuration'] and info['configuration_provenance']
        baseline = await inspect(group_path=path, node='Hero Surface')
        for inputs in [{coat: .8, 'missing': .2}, {coat: 2.}, {coat: True}]:
            invalid = await client.call_tool('assign_material', {'action': 'set_inputs',
                'material_name': 'ArtistFinish', 'group_path': path, 'node': 'Hero Surface',
                'inputs': inputs, 'lease_id': lease})
            assert invalid.is_error
            assert await inspect(group_path=path, node='Hero Surface') == baseline
        old_update = await client.call_tool('assign_material', {'names': ['Cube'],
            'material_name': 'ManagedA', 'update_existing': True, 'roughness': .9, 'lease_id': lease})
        assert old_update.is_error
        await call('asset_io', action='save', path='authored-finish.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'tool_count': len(catalog.tools),
            'nested_groups': 2, 'shared_material_owners': 4, 'per_material_controls_independent': True,
            'links_preserved': True, 'linked_fallback_retained': True,
            'managed_configs_detached': changed['managed_materials_detached'],
            'invalid_edits_preserved_inputs': True, 'native_shader_saved': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('shader_input_fixture.py'))
