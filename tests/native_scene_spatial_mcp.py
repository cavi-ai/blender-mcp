"""Read-only evaluated spatial queries through actual MCP and a private headless bridge."""
import hashlib
import json
import math
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main

from cavi_blender_mcp.client import BridgeClient, BridgeOperationError


async def exercise(root, env, parameters=None):
    parameters = parameters or StdioServerParameters(command=sys.executable,
        args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(parameters) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            return result.structured_content

        async def spatial(subjects=('Shelter',), context=('Above',), **changes):
            if changes:
                # Internal transform/budget regression coverage uses only this fixture's bridge.
                result = BridgeClient(root/'connection.json').call('inspect_scene_spatial',
                    {'subjects': list(subjects), 'context': list(context), **changes})
            else:
                result = await call('scene_info', spatial=[subjects[0], context[0]])
            assert result['scope'] == 'scene_spatial_inspection', result
            report = result['spatial']
            assert 'solid_containment' in report['not_checked'] and 'all_clear' not in report, report
            return report

        initial_hash = hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        before = json.loads((root/'audit.json').read_text())
        original = await spatial()
        assert original['intersections']['triangle_pairs'] == 0, original
        assert abs(original['nearest']['distance_m'] - 1) < 1e-6, original
        assert original['subjects'][0]['world_bounds_m'] == [[1., 0., 0.], [3., 1., 0.]], original
        crossing = await spatial(context=('Crossing',))
        assert crossing['intersections']['triangle_pairs'] > 0, crossing
        assert crossing['intersections']['examples'][0]['subject']['object'] == 'Shelter', crossing
        sparse = await spatial(context=('SparseTown',))
        assert sparse['bounds_overlap'], sparse
        assert sparse['intersections']['triangle_pairs'] == 0, sparse
        assert abs(sparse['nearest']['distance_m'] - 2) < 1e-6, sparse
        delta = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 1], [0, 0, 0, 1]]
        moved = await spatial(proposed_world_delta=delta)
        assert moved['intersections']['triangle_pairs'] > 0, moved
        assert moved['intersections']['coplanar_pairs_added'] > 0, moved
        assert moved['subjects'][0]['world_bounds_m'] == [[1., 0., 1.], [3., 1., 1.]], moved
        assert moved['geometry_identity']['sha256'] == original['geometry_identity']['sha256'], moved
        assert moved['query_sha256'] != original['query_sha256'], moved
        repeated = await spatial()
        assert repeated == original, (original, repeated)
        generated = await spatial(subjects=('Generated',))
        assert generated['subjects'][0]['triangles'] == 12, generated
        assert generated['subjects'][0]['world_bounds_m'] == [[0., 3., -1.], [1., 4., 0.]], generated
        assert math.isclose(generated['nearest']['distance_m'], 1, abs_tol=1e-6), generated
        contained = await spatial(context=('Enclosing',))
        assert contained['intersections']['triangle_pairs'] == 0, contained
        assert contained['nearest']['distance_m'] > 0, contained
        for changes in ({'max_triangles': 1}, {'max_pair_tests': 1},
                        {'proposed_world_delta': [[0]*4]*4},
                        {'proposed_world_delta': [[1, 0, 0, 1e300], [0, 1, 0, 0],
                                                   [0, 0, 1, 0], [0, 0, 0, 1]]}):
            try:
                BridgeClient(root/'connection.json').call('inspect_scene_spatial',
                    {'subjects': ['Shelter'], 'context': ['Crossing'], **changes})
            except BridgeOperationError:
                pass
            else:
                raise AssertionError('Internal spatial validation did not reject invalid input')
        for value in (['Unknown', 'Above'], ['Shelter', 'Shelter'], ['Shelter'],
                      ['Shelter', 'Above', 'Crossing'],
                      {'subjects': ['Shelter'], 'context': ['Above']},
                      {'subjects': ['Shelter'], 'context': ['Above'], 'max_triangles': 1}):
            result = await client.call_tool('scene_info', {'spatial': value})
            assert result.is_error, result
        assert not (await call('scene_info', limit=1))['source_state']['dirty']
        assert hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest() == initial_hash
        owner = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='spatial-native',
            expected_project=owner['project_id']))['lease_id']
        await call('asset_io', action='save', path='after.blend', lease_id=lease)
        assert json.loads((root/'audit.json').read_text()) == before
        await call('session_control', action='release', lease_id=lease)
        return {'scene_spatial_inspection': 'passed', 'separated': original,
                'intersecting': crossing, 'sparse_context': sparse, 'internal_proposed': moved,
                'evaluated_modifier': generated, 'containment_not_claimed': contained,
                'scene_state_unchanged': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('scene_spatial_fixture.py'))
