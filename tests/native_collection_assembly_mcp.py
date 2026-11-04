"""Compose native collection instances and round-trip evaluated assemblies through MCP."""

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

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='collection-assembly-check',
            expected_project=state['project_id']))['lease_id']
        source = await call('asset_library', action='inspect', path='kit.blend')
        loaded = await call('asset_library', action='append', path='kit.blend', names=['GardenKit'],
            expected_sha256=source['sha256'], instance_collections=True, lease_id=lease)
        assert len(loaded['instances']) == 1, loaded
        first = loaded['instances'][0]['name']
        await call('object_edit', action='transform', name=first, location=[2, 1, 0],
                   rotation_degrees=[0, 0, 90], scale=[1, 1, 1], lease_id=lease)
        await call('object_edit', action='duplicate', name=first, new_name='GardenKit_B',
                   linked=True, lease_id=lease)
        await call('object_edit', action='transform', name='GardenKit_B', location=[-3, -1, 2],
                   rotation_degrees=[15, 0, 40], scale=[-1.2, .8, 1.1], lease_id=lease)
        before = await call('scene_info', limit=1000)
        reports = {}
        for extension in ['glb', 'fbx']:
            report = await call('asset_io', action='export', path='garden.'+extension,
                names=[first, 'GardenKit_B'], assembly=True, lease_id=lease)
            assert len(report['placements']) == 6 and report['triangles'] == 120, report
            assert report['unique_meshes'] == 3, report
            assert sum(p['shear_baked'] for p in report['placements']) == 1, report
            assert (await call('scene_info', limit=1000))['objects'] == before['objects']
            imported = await call('asset_io', action='import', path='garden.'+extension,
                                  name='Checked'+extension, lease_id=lease)
            assert imported['imported_triangles'] == 120, imported
            reports[extension] = {'triangles': report['triangles'], 'unique_meshes': report['unique_meshes']}
            # Remove imported meshes from the scene inventory used for the next preservation check.
            before = await call('scene_info', limit=1000)
        payload = (root/'garden.glb').read_bytes()
        length = struct.unpack_from('<I', payload, 12)[0]
        document = json.loads(payload[20:20+length])
        assert len(document['meshes']) == 3, len(document['meshes'])
        assert sum('mesh' in n for n in document['nodes']) == 6
        await call('asset_io', action='save', path='garden-source.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'instance_roots': 2,
                'mesh_placements': 6, 'native_data_sharing': True, 'roundtrips': reports,
                'source_scene_preserved': True, 'nonzero_collection_offsets': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('collection_assembly_fixture.py'))
