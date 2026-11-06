"""One private native MCP case: inspect, extrude, preserve artist data and reopen."""
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m','cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            result = await client.call_tool(tool, args)
            assert not result.is_error, result
            return result.structured_content

        before = await call('scene_info', name='Panel', faces=True)
        assert before['total'] == 7 and len(before['faces']) == 7
        page = await call('scene_info', name='Panel', faces=True, offset=5, limit=1)
        assert page['faces'] == before['faces'][5:6] and page['mesh_sha256'] == before['mesh_sha256']
        top = [f['index'] for f in before['faces'] if f['normal_local'][2] > .9]
        assert len(top) == 2
        args = {'action':'extrude_faces','name':'Panel','face_indices':top,'offset':[0,0,.4]}
        assert (await client.call_tool('mesh_edit', args)).is_error
        status = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='mesh-region-case',
            expected_project=status['project_id']))['lease_id']
        assert (await client.call_tool('mesh_edit', {**args,'lease_id':lease})).is_error
        assert (await call('scene_info',name='Panel',faces=True))['mesh_sha256'] == before['mesh_sha256']
        await call('object_edit',action='make_single_user',name='Panel',lease_id=lease)
        for invalid in ({'expected_mesh_sha256':'0'*64}, {'offset':[.4,0,0]},
                        {'face_indices':list(range(7))}, {'face_indices':[999]}):
            rejected = await client.call_tool('mesh_edit', {**args, **invalid, 'lease_id':lease})
            assert rejected.is_error
            assert (rejected.structured_content or {}).get('error',{}).get('outcome') == 'rejected', rejected
            assert (await call('scene_info',name='Panel',faces=True))['mesh_sha256'] == before['mesh_sha256']
        result = await call('mesh_edit', **args, expected_mesh_sha256=before['mesh_sha256'], lease_id=lease)
        edit = result['extrusion']
        assert edit['vertices_added'] == 4 and edit['triangles_after'] == 20, edit
        assert len(edit['cap_faces']) == 2 and len(edit['side_faces']) == 4, edit
        assert edit['uv_status'] == 'new_side_faces_require_layout'
        after = await call('scene_info',name='Panel',faces=True)
        assert after['total'] == 11 and after['mesh_sha256'] == edit['mesh_sha256_after']
        assert (await call('scene_info',name='Peer',faces=True))['mesh_sha256'] == before['mesh_sha256']
        quality = await call('inspect_mesh_quality', names=['Panel'], checks=['topology'])
        topology = quality['objects'][0]['checks']['topology']
        assert topology['boundary_edges'] == topology['non_manifold_edges'] == topology['zero_area_faces'] == 0, topology
        native = json.loads((root/'native-check.json').read_text())
        assert native['artist_uv_and_float_color_preserved'] and native['object_finish_preserved']
        await call('asset_io', action='save', path='extruded.blend',lease_id=lease)
        await call('asset_io', action='open', path='initial.blend',lease_id=lease)
        await call('asset_io', action='open', path='extruded.blend',lease_id=lease)
        reopened = await call('scene_info',name='Panel',faces=True)
        assert reopened['mesh_sha256'] == after['mesh_sha256']
        native = json.loads((root/'native-check.json').read_text())
        assert native['file'] == str(root/'extruded.blend'), native
        await call('session_control', action='release', lease_id=lease)
        return {'native_mcp_region_extrusion':'passed','connected_cap_faces':2,'side_faces':4,
            'triangles':20,'stale_selection_and_degenerate_offsets_rejected':True,
            'artist_data':native,'saved_project_roundtrip':'passed','side_uvs':'layout_required'}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('mesh_regions_fixture.py'))
