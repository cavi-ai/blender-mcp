"""One private MCP case: physical density targets on a rigged source UV chart."""
import json
import math
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env, parameters=None):
    params = parameters or StdioServerParameters(command=sys.executable,
        args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            result = await client.call_tool(tool, args)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='density-native-case',
                           expected_project=state['project_id']))['lease_id']
        saves = 0

        async def snapshot():
            nonlocal saves
            saves += 1
            await call('asset_io', action='save', path=f'density-{saves}.blend', lease_id=lease)
            return json.loads((root/'density-audit.json').read_text())

        before = await snapshot()
        pages = [await call('scene_info', name='TileGrid', faces=True, uv_layer='UVMap',
                            limit=1, offset=offset) for offset in (0,1)]
        assert pages[0]['mesh_sha256'] == pages[1]['mesh_sha256'] == before['geometry']
        assert pages[0]['uv'] == pages[1]['uv'] and pages[0]['uv']['charts'] == 2
        assert [page['faces'][0]['uv']['chart'] for page in pages] == [0,1]
        assert [page['faces'][0]['uv']['pinned_loops'] for page in pages] == [1,1]
        assert all(page['faces'][0]['uv']['chart_faces'] == 1 for page in pages)
        collapsed = await call('scene_info', name='TileGrid', faces=True, uv_layer='Alternate')
        assert collapsed['uv']['charts'] == 1
        assert [face['uv']['chart_faces'] for face in collapsed['faces']] == [2,2]
        continuous = [await call('scene_info', name='TileGrid', faces=True, uv_layer='Continuous',
                                 limit=1, offset=offset) for offset in (0,1)]
        assert continuous[0]['uv'] == continuous[1]['uv']
        assert [p['faces'][0]['uv']['chart'] for p in continuous] == [0,0]
        assert [p['faces'][0]['uv']['chart_faces'] for p in continuous] == [2,2]
        empty = await call('scene_info', name='TileGrid', faces=True, uv_layer='UVMap', offset=100)
        assert empty['faces'] == [] and empty['uv'] == pages[0]['uv']
        legacy = await call('scene_info', name='TileGrid', faces=True)
        assert 'uv' not in legacy and all('uv' not in face for face in legacy['faces'])
        diagnostics = await call('inspect_uv_layout', names=['Diagnostic','DiagnosticTwin'],
            uv_layer='InspectUV', texture_resolution=[2048,1024], padding_pixels=8,
            material='ArtistFinish')
        assert diagnostics['overlap']['triangle_pairs'] > 0 and diagnostics['charts'] == 4
        expected_faces = {0:0, 1:0, 4:2, 5:2}
        for key in ('overlap','padding'):
            assert diagnostics[key]['examples']
            for example in diagnostics[key]['examples']:
                assert len(example['sources']) == 2
                for source in example['sources']:
                    assert source['object'] in ('Diagnostic','DiagnosticTwin')
                    assert source['face'] == expected_faces[source['source_triangle']]
        diagnostic_page = await call('scene_info', name='Diagnostic', faces=True, uv_layer='InspectUV')
        assert [f['uv']['chart'] for f in diagnostic_page['faces']] == [0,1,2]
        assert all(o['uv_sha256'] == diagnostic_page['uv']['sha256'] for o in diagnostics['objects'])
        assert all(o['mesh_sha256'] == diagnostic_page['mesh_sha256'] for o in diagnostics['objects'])
        assert not (await call('scene_info', limit=1))['source_state']['dirty']
        assert await snapshot() == before
        selected = [f['index'] for page in pages for f in page['faces'] if f['uv']['chart'] == 0]
        region = {'bounds': [1, 1, 2, 2], 'texture_resolution': [2048, 1024],
                  'margin_px': 8, 'allow_pinned': True}
        args = {'action': 'uv_transform', 'name': 'TileGrid', 'uv_layer': 'UVMap',
                'uv_transform': {'faces': selected, 'pivot': [1.5, 1.5]}, 'uv_region': region,
                'target_px_per_m': 512, 'expected_mesh_sha256': before['geometry'], 'lease_id': lease}
        for invalid in ({'target_px_per_m': 100000}, {'expected_mesh_sha256': '0'*64},
                        {'uv_region': {**region, 'bounds': [0, 0, 1, 1]}},
                        {'uv_region': {**region, 'allow_pinned': False}}, {'uv_layer': 'Missing'}):
            result = await client.call_tool('mesh_edit', {**args, **invalid})
            assert result.is_error and result.structured_content['error']['outcome'] == 'rejected', result
            assert not (await call('scene_info', limit=1))['source_state']['dirty']
            assert await snapshot() == before
        densities = {}
        for target in (512, 1024):
            result = await call('mesh_edit', **{**args, 'target_px_per_m': target})
            density = result['uv_transform']['density']
            assert density['geometry_scope'] == 'unevaluated_world_linear'
            assert math.isclose(density['after']['world_area_m2'], .0012, rel_tol=1e-6), density
            assert math.isclose(density['after']['density_area_weighted'], target, rel_tol=1e-4), density
            assert density['quality']['passed'] and density['relative_error'] <= 1e-4
            current = await snapshot()
            uv = current['uvs']['UVMap'][:4]
            area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(uv, uv[1:]+uv[:1], strict=True)))/2
            # 1x2 source units, object scale 2x3, centimetre scene units: .0012 m².
            assert math.isclose(area, target*target*.0012/(2048*1024), rel_tol=3e-4), area
            assert current['uvs']['UVMap'][4:] == before['uvs']['UVMap'][4:]
            assert all(current['uvs'][key] == value for key,value in before['uvs'].items() if key != 'UVMap')
            assert all(current[k] == v for k,v in before.items() if k != 'uvs')
            assert math.isclose(density['before']['anisotropy_max'], density['after']['anisotropy_max'], rel_tol=1e-4)
            densities[str(target)] = {'measured_px_per_m': density['after']['density_area_weighted'],
                'independent_uv_area': area, 'relative_error': density['relative_error']}
        final_file = f'density-{saves}.blend'
        corrected = await call('scene_info', name='TileGrid', faces=True, uv_layer='UVMap')
        assert corrected['mesh_sha256'] == pages[0]['mesh_sha256']
        assert corrected['uv']['sha256'] != pages[0]['uv']['sha256']
        await call('asset_io', action='open', path='initial.blend', lease_id=lease)
        await call('asset_io', action='open', path=final_file, lease_id=lease)
        assert json.loads((root/'density-audit.json').read_text()) == current
        reopened = await call('scene_info', name='TileGrid', faces=True, uv_layer='UVMap')
        assert reopened['uv'] == corrected['uv'] and reopened['faces'] == corrected['faces']
        await call('session_control', action='release', lease_id=lease)
        return {'selected_density_targets': densities, 'world_area_m2': .0012,
            'source_rejections': 5, 'rig_keys_weights_pins_colors_and_context': 'preserved',
            'unselected_uvs_and_layers': 'preserved', 'save_reopen': 'passed',
            'chart_pages_and_hashes': 'passed', 'filtered_cross_object_face_diagnostics': 'passed'}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('uv_density_fixture.py'))
