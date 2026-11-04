"""Real MCP native-library append preserves procedural, rig and image dependencies."""

import json
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

        original = await call('scene_info', limit=100)
        inspected = await call('asset_library', action='inspect', path='kit.blend')
        assert inspected['names'] == ['EditableKit'], inspected
        assert (await call('scene_info', limit=100))['objects'] == original['objects']
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='native-library-check',
            expected_project=state['project_id']))['lease_id']
        appended = await call('asset_library', action='append', path='kit.blend',
            names=['EditableKit'], expected_sha256=inspected['sha256'], lease_id=lease)
        assert appended['roots'][0]['asset'], appended
        expected = json.loads((root/'expected.json').read_text())
        assert appended['images'][0]['sha256'] == expected['packed_sha256'], appended

        def name(receipt, source_name):
            return next(i['name'] for i in receipt['items'] if i['source_name'] == source_name and i['id_type'] == 'OBJECT')

        fence, rig, skin = [name(appended, n) for n in ['Fence', 'LibraryRig', 'LibrarySkin']]
        assert fence != 'Fence'
        inspection = await call('geometry_nodes', action='inspect', name=fence)
        generator = inspection['modifiers'][0]
        identifier = next(s['identifier'] for s in generator['inputs'] if s['name'] == 'Count')
        await call('geometry_nodes', action='set_inputs', name=fence, modifier=generator['name'],
            inputs={identifier: 7}, lease_id=lease)
        checked_rig = await call('inspect_rig', armature=rig, meshes=[skin])
        assert checked_rig['deform_bones'] == 1 and checked_rig['active_action'], checked_rig
        assert checked_rig['meshes'][0]['weights']['unweighted_vertices'] == 0, checked_rig
        second = await call('asset_library', action='append', path='kit.blend', names=['EditableKit'],
            expected_sha256=inspected['sha256'], lease_id=lease)
        other = (await call('geometry_nodes', action='inspect', name=name(second, 'Fence')))['modifiers'][0]
        assert other['node_group'] != generator['node_group']
        assert next(s['value'] for s in other['inputs'] if s['name'] == 'Count') == 3
        before = await call('scene_info', limit=100)
        bad_source = await call('asset_library', action='inspect', path='broken.blend', kind='materials')
        result = await client.call_tool('asset_library', {'action': 'append', 'path': 'broken.blend',
            'kind': 'materials', 'names': ['BrokenFinish'], 'expected_sha256': bad_source['sha256'], 'lease_id': lease})
        assert result.is_error, result
        assert (await call('scene_info', limit=100))['objects'] == before['objects']
        assert (await call('scene_info', name='Fence'))['modifiers'] == []
        material = await call('asset_library', action='append', path='kit.blend', kind='materials',
            names=['Blue'], expected_sha256=inspected['sha256'], lease_id=lease)
        group = await call('asset_library', action='append', path='kit.blend', kind='node_groups',
            names=[next(i['source_name'] for i in appended['items']
                        if i['id_type'] == 'NODETREE' and i['name'] == generator['node_group'])],
            expected_sha256=inspected['sha256'], lease_id=lease)
        assert material['roots'][0]['name'] != 'Blue'
        assert group['roots'][0]['asset']
        objects = await call('asset_library', action='append', path='kit.blend', kind='objects',
            names=['LibraryRig', 'LibrarySkin'], expected_sha256=inspected['sha256'], lease_id=lease)
        object_names = {i['source_name']: i['name'] for i in objects['roots']}
        assert (await call('inspect_rig', armature=object_names['LibraryRig'],
                           meshes=[object_names['LibrarySkin']]))['deform_bones'] == 1
        await call('asset_io', action='save', path='consumer.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'collections_appended': 2,
                'independent_node_groups': True, 'rig_and_skin_preserved': True,
                'packed_texture_sha256': expected['packed_sha256'], 'source_sha256': inspected['sha256'],
                'collision_mapping': fence, 'failed_append_preserved_scene': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('asset_library_fixture.py'))
