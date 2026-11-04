"""Real MCP parameter edits, source isolation, snapshot and GLB acceptance."""

import json
import struct
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()

        async def call(tool_name, **arguments):
            result = await client.call_tool(tool_name, arguments)
            assert not result.is_error, result
            return result.structured_content

        async def inspect(name='Fence'):
            return (await call('geometry_nodes', action='inspect', name=name))['modifiers'][0]

        original = await inspect()
        fields = {s['name']: s for s in original['inputs']}
        identifiers = {name: s['identifier'] for name, s in fields.items()}
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='procedural-asset-check',
            expected_project=state['project_id']))['lease_id']

        async def edit(**kwargs):
            return await call('geometry_nodes', name='Fence', lease_id=lease, **kwargs)

        values = {'Count': 6, 'Spacing': .8, 'Width': .12, 'Height': 1.8, 'Offset': [.25, 0, .9],
                  'Finish': {'name': 'Blue', 'id_type': 'MATERIAL'}, 'Label': 'Wide fence', 'Tint': [.1, .2, .3, 1],
                  'Enabled': True, 'Rotation': [.1, .2, .3]}
        await edit(action='set_inputs', modifier='Generator', inputs={identifiers[k]: v for k, v in values.items()})
        changed = await inspect()
        assert (changed['node_group'], changed['nodes'], changed['links']) == (
            original['node_group'], original['nodes'], original['links'])
        other = await inspect('OtherFence')
        assert next(s for s in other['inputs'] if s['name'] == 'Count')['value'] == 3
        assert next(s for s in changed['inputs'] if s['name'] == 'Count')['value'] == 6
        for bad in [{identifiers['Spacing']: 2, identifiers['Count']: 6.5},
                    {identifiers['Spacing']: 2, identifiers['Tint']: [1e100, 0, 0, 1]},
                    {identifiers['Count']: 0}, {'not_a_socket': 1},
                    {identifiers['Finish']: {'name': 'Blue', 'id_type': 'OBJECT'}}]:
            result = await client.call_tool('geometry_nodes', {'action': 'set_inputs', 'name': 'Fence',
                'modifier': 'Generator', 'inputs': bad, 'lease_id': lease})
            assert result.is_error, result
            assert await inspect() == changed
        if fields['Mask']['attribute_supported']:
            await edit(action='set_inputs', modifier='Generator', attributes={identifiers['Mask']: 'finish_mask'})
            await edit(action='set_inputs', modifier='Generator', inputs={identifiers['Mask']: .25})
            mask = next(s for s in (await inspect())['inputs'] if s['name'] == 'Mask')
            assert mask['use_attribute'] and mask['attribute_name'] == 'finish_mask', mask
            await edit(action='set_inputs', modifier='Generator', attributes={identifiers['Mask']: None})
        else:
            raise AssertionError('Fixture must exercise attribute-capable inputs')
        baked = await edit(action='bake_copy', new_name='Fence_LOD0')
        assert baked['triangles'] == 72 and not baked['modifiers'], baked
        assert next(s for s in baked['material_triangles'] if s['material'] == 'Blue')['triangles'] == 72, baked
        assert abs(baked['dimensions'][0]-4.12) < 1e-5 and abs(baked['dimensions'][2]-1.8) < 1e-5, baked
        await call('asset_io', action='export', path='fence.glb', names=['Fence_LOD0'], lease_id=lease)
        payload = (root/'fence.glb').read_bytes()
        length = struct.unpack_from('<I', payload, 12)[0]
        document = json.loads(payload[20:20+length])
        used = {p['material'] for mesh in document['meshes'] for p in mesh['primitives']}
        assert len(used) == 1, used
        color = document['materials'][used.pop()]['pbrMetallicRoughness']['baseColorFactor']
        assert all(abs(a-b) < 1e-6 for a, b in zip(color, [.05, .2, .8, 1], strict=True)), color
        imported = await call('asset_io', action='import', path='fence.glb', name='CheckedFence', lease_id=lease)
        assert imported['imported_triangles'] == 72, imported
        mesh_name = next(item['name'] for item in imported['objects'] if item['type'] == 'MESH')
        mesh = await call('scene_info', name=mesh_name)
        assert all(abs(a-b) < 1e-5 for a, b in zip(mesh['dimensions'], baked['dimensions'], strict=True)), mesh
        assert len(mesh['materials']) == 1, mesh
        await call('asset_io', action='save', path='fence-source.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'source_count': 3, 'variant_count': 6,
                'source_graph_preserved': True, 'invalid_batch_preserved_inputs': True,
                'native_setter_rollback': True,
                'named_attribute_roundtrip': True, 'snapshot_triangles': baked['triangles'],
                'glb_triangles': imported['imported_triangles'], 'dimensions': baked['dimensions']}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('procedural_asset_fixture.py'))
