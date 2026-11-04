"""Real MCP material overrides inside an independent kit preserve shared geometry."""

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

        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='instance-material-check',
            expected_project=state['project_id']))['lease_id']
        source = await call('asset_library', action='inspect', path='kit.blend')
        loaded = await call('asset_library', action='append', path='kit.blend', names=['GardenKit'],
            expected_sha256=source['sha256'], instance_collections=True, lease_id=lease)
        a = loaded['instances'][0]['name']
        await call('object_edit', action='duplicate', name=a, new_name='Kit_B', linked=True, lease_id=lease)
        fork = await call('object_edit', action='make_unique', name='Kit_B', new_name='FinishedKit', lease_id=lease)

        def member(name):
            return next(i['name'] for i in fork['items'] if i['id_type'] == 'OBJECT' and i['source_name'] == name)

        base, trim = member('BaseStone'), member('TrimStone')
        original = await call('scene_info', name=a, definition=True)
        before = await call('scene_info', name='Kit_B', definition=True)
        rejected = await client.call_tool('assign_material', {'names': [base], 'material_name': 'WrongDataFinish',
            'instance': 'Kit_B', 'lease_id': lease})
        assert rejected.is_error
        finish = await call('assign_material', names=[base], material_name='VariantFinish',
            instance='Kit_B', link_mode='OBJECT', base_color=[.3, .4, .5, 1.], roughness=.3,
            base_color_texture='color.png', roughness_texture='roughness.png', normal_texture='normal.png',
            normal_strength=.6, uv_scale=[2., 1.5], lease_id=lease)
        assert finish['bindings'][0]['link_mode'] == 'OBJECT' and finish['bindings'][0]['mesh_users'] == 2, finish
        assert not finish['reserved_empty_slots']
        updated = await call('assign_material', names=[base], material_name='VariantFinish', instance='Kit_B',
            update_existing=True, normal_strength=.7, roughness=.4, lease_id=lease)
        assert updated['bindings'][0]['link_mode'] == 'OBJECT'
        assert updated['config']['uv_scale'] == [2., 1.5] and len(updated['textures']) == 3
        changed = await call('scene_info', name='Kit_B', definition=True)
        rows = {v['name']: v for v in changed['objects']}
        old_rows = {v['name']: v for v in before['objects']}
        assert rows[base]['material_slots'] == [{'index': 0, 'material': 'VariantFinish', 'link': 'OBJECT'}]
        assert rows[trim] == old_rows[trim]
        assert (await call('scene_info', name=a, definition=True)) == original
        for names in [['Cube'], [base, 'Camera']]:
            rejected = await client.call_tool('assign_material', {'names': names, 'material_name': 'Rejected',
                'instance': 'Kit_B', 'link_mode': 'OBJECT', 'lease_id': lease})
            assert rejected.is_error
            assert (await call('scene_info', name='Kit_B', definition=True)) == changed
        exported = await call('asset_io', action='export', path='finished.glb', names=['Kit_B'], assembly=True, lease_id=lease)
        assert exported['triangles'] == 60, exported
        payload = (root/'finished.glb').read_bytes()
        size = struct.unpack_from('<I', payload, 12)[0]
        document = json.loads(payload[20:20+size])
        material = next(i for i, m in enumerate(document['materials']) if m['name'] == 'VariantFinish')
        triangles = sum(document['accessors'][p['indices']]['count']//3 for m in document['meshes']
                        for p in m['primitives'] if p.get('material') == material)
        assert triangles == 12, triangles
        imported = await call('asset_io', action='import', path='finished.glb', name='CheckedFinish', lease_id=lease)
        assert imported['imported_triangles'] == 60
        await call('asset_io', action='save', path='finished.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'object_link_preserved_on_update': True,
                'mesh_users': 2, 'source_and_sibling_bindings_unchanged': True,
                'invalid_targets_preserved_bindings': True, 'source_maps_bit_depth': 16,
                'exported_finish_triangles': triangles, 'reimported_triangles': imported['imported_triangles']}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('instance_material_fixture.py'))
