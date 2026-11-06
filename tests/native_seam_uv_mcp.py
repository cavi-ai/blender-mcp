"""One private MCP case for explicit seam flags and seam-aware UV strips."""
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            result = await client.call_tool(tool, args)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='seam-native-case',
                           expected_project=state['project_id']))['lease_id']

        async def audit():
            await call('inspect_mesh_quality', names=['Sleeve'], checks=['topology'])
            return json.loads((root/'seam-audit.json').read_text())

        pages = [await call('scene_info', name='Sleeve', edges=True, limit=3)]
        for offset in range(3, pages[0]['total'], 3):
            pages.append(await call('scene_info', name='Sleeve', edges=True, limit=3, offset=offset))
        assert all(p['mesh_sha256'] == pages[0]['mesh_sha256'] for p in pages)
        rows = [e for p in pages for e in p['edges']]
        assert len(rows) == 24 and all(e['face_count'] == 2 and len(e['faces']) == 2 for e in rows)
        cut = [e['index'] for e in rows if e['center_local'][0] < -.99 and .49 < e['center_local'][2] < .51]
        assert len(cut) == 1
        cut_vertices = next(e['vertices'] for e in rows if e['index'] == cut[0])
        polygons = (await call('scene_info', name='Sleeve', faces=True))['faces']
        cut_faces = [f for f in polygons if f['index'] < 8 and set(cut_vertices) <= set(f['vertices'])]
        assert len(cut_faces) == 2
        before = await audit()
        args = {'action': 'set_seams', 'name': 'Sleeve', 'edge_indices': cut, 'seam': True,
                'expected_mesh_sha256': pages[0]['mesh_sha256'], 'lease_id': lease}
        for invalid in ({'edge_indices': [9999]}, {'expected_mesh_sha256': '0'*64}):
            rejected = await client.call_tool('mesh_edit', {**args, **invalid})
            assert rejected.is_error and rejected.structured_content['error']['outcome'] == 'rejected', rejected
            assert (await audit()) == before
            assert not (await call('scene_info', limit=1))['source_state']['dirty']
        for enabled, changed in ((True, 1), (True, 0), (False, 1), (True, 1)):
            result = await call('mesh_edit', **{**args, 'seam': enabled})
            assert result['seam_edit']['changed'] == changed, result
            current = await audit()
            assert current['seams'][cut[0]] == enabled
            assert all(a == b for i, (a, b) in enumerate(zip(before['seams'], current['seams'], strict=True)) if i not in cut)
            assert all(current[k] == v for k, v in before.items() if k != 'seams')
        marked = await audit()
        methods = {}
        loops = {i for face in range(8) for i in before['loops'][str(face)]}
        for method in ('smart', 'conformal', 'angle_based', 'minimum_stretch'):
            result = await call('mesh_edit', action='unwrap_faces', name='Sleeve', face_indices=list(range(8)),
                uv_layer='BakeAtlas', unwrap_method=method, expected_mesh_sha256=before['geometry'],
                uv_region={'bounds': [.5, .05, .98, .95], 'texture_resolution': [2048, 1024], 'margin_px': 8},
                lease_id=lease)
            report = result['face_unwrap']
            assert report['unwrap_method'] == method and report['quality']['passed'], report
            assert report['quality']['charts'] > 1 if method == 'smart' else report['quality']['charts'] == 1, report
            current = await audit()
            assert current['seams'] == marked['seams']
            assert current['uvs']['ArtistUV'] == before['uvs']['ArtistUV']
            assert all(a == b for i, (a, b) in enumerate(zip(before['uvs']['BakeAtlas'], current['uvs']['BakeAtlas'], strict=True)) if i not in loops)
            assert all(current[k] == v for k, v in before.items() if k not in ('seams', 'uvs'))
            if method != 'smart':
                for vertex in cut_vertices:
                    ends = [current['uvs']['BakeAtlas'][before['loops'][str(f['index'])][f['vertices'].index(vertex)]]
                            for f in cut_faces]
                    assert max(abs(a-b) for a, b in zip(*ends, strict=True)) > .01, ends
            methods[method] = report['quality']
        await call('asset_io', action='save', path='seam-finished.blend', lease_id=lease)
        await call('asset_io', action='open', path='initial.blend', lease_id=lease)
        await call('asset_io', action='open', path='seam-finished.blend', lease_id=lease)
        assert await audit() == current
        assert not list(root.glob('.cavi-uv-*'))
        await call('session_control', action='release', lease_id=lease)
        return {'seam_edges': 'passed', 'blender': before['blender'],
            'native_methods': before['native_unwrap_methods'], 'projections': methods,
            'seam_strip_and_explicit_cut': 'passed',
            'protected_data_and_context': 'passed', 'save_reopen': 'passed', 'worker_cleanup': 'passed'}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('seam_uv_fixture.py'))
