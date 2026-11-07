"""One MCP case: source-point translation retains morphs, skin, UVs and context."""
import hashlib
import json
import math
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env, parameters=None, proportional=False, symmetry=False):
    params = parameters or StdioServerParameters(command=sys.executable,
        args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            result = await client.call_tool(tool,args)
            assert not result.is_error, result
            return result.structured_content

        target = await call('scene_info',limit=1)
        assert Path(target['workspace']).resolve() == root.resolve(), 'Native fixture workspace mismatch'
        assert Path(target['file']).resolve() == (root/'initial.blend').resolve(), 'Native fixture source mismatch'
        assert target['source_state']['saved_source']['sha256'] == hashlib.sha256((root/'initial.blend').read_bytes()).hexdigest()
        state = await call('session_control',action='inspect')
        lease = (await call('session_control',action='claim',owner='vertex-native-case',
                           expected_project=state['project_id']))['lease_id']
        sequence = 0

        async def snapshot():
            nonlocal sequence
            sequence += 1
            await call('asset_io',action='save',path=f'vertices-{sequence}.blend',lease_id=lease)
            return json.loads((root/'vertex-audit.json').read_text())

        before = await snapshot()
        assert before['objects']['TileGrid']['animation']['curves']
        named = await call('scene_info',name='TileGrid')
        assert named['vertices'] == len(before['objects']['TileGrid']['vertices'])
        vertex_count = 10 if proportional else 6
        pages = [await call('scene_info',name='TileGrid',vertices=True,limit=3,offset=i)
                 for i in range(0,vertex_count,3)]
        assert pages[0]['mesh_sha256'] == pages[1]['mesh_sha256']
        assert [v['index'] for p in pages for v in p['vertices']] == list(range(vertex_count))
        selected = [0] if proportional or symmetry else [v['index'] for p in pages for v in p['vertices']
                    if v['position_local'][1] == -1 and v['position_local'][0] <= 0]
        assert selected == ([0] if proportional or symmetry else [0,1])
        weights = {0:1.,1:.648,4:1.} if symmetry else ({0:1.,1:.648,4:.104} if proportional else {0:1.,1:1.})

        def displacement(index):
            x = 0. if symmetry and index == 1 else (-.25 if symmetry and index == 4 else .25)
            return [x,.125,.5]
        empty = await call('scene_info',name='TileGrid',vertices=True,offset=100)
        assert empty['vertices'] == [] and empty['total'] == vertex_count
        assert await snapshot() == before
        args = {'action':'move_vertices','name':'TileGrid','vertex_indices':selected,
                'offset':[.25,.125,.5],'expected_mesh_sha256':pages[0]['mesh_sha256'],'lease_id':lease}
        if proportional or symmetry:
            args['amount'] = .05
        if symmetry:
            args.update(symmetry_axis='X',symmetry_tolerance_m=.00001)
        invalid_inputs = [{'vertex_indices':[vertex_count]}, {'vertex_indices':[0,0]}, {'offset':[0,0,0]},
                          {'expected_mesh_sha256':'0'*64}, {'name':'SharedA'}, {'lease_id':'other'}]
        if proportional or symmetry:
            invalid_inputs += [{'amount':0},{'amount':-1}]
        if symmetry:
            invalid_inputs += [{'vertex_indices':[0,4]}, {'symmetry_tolerance_m':.1},
                {'name':'Static','symmetry_tolerance_m':1e-8}]
        for invalid in invalid_inputs:
            rejected = await client.call_tool('mesh_edit',{**args,**invalid})
            assert rejected.is_error, rejected
            # The shared lease guard conservatively reports RuntimeError as unknown.
            # Inspect source and ownership before proceeding; never replay the refused call.
            outcome = 'unknown' if 'lease_id' in invalid else 'rejected'
            assert rejected.structured_content['error']['outcome'] == outcome, rejected
            assert not (await call('scene_info',limit=1))['source_state']['dirty']
            assert await snapshot() == before
        receipts = {}
        for name in ('TileGrid','Absolute','Static'):
            page = await call('scene_info',name=name,vertices=True)
            result = await call('mesh_edit',**{**args,'name':name,'expected_mesh_sha256':page['mesh_sha256']})
            edit = result['vertex_edit']
            assert edit['changed_vertices'] == len(weights) and edit['max_shape_delta_error_local'] < 1e-6, edit
            assert edit['vertex_indices'] == list(weights)
            if proportional or symmetry:
                falloff = edit['falloff']
                assert falloff['mode'] == 'source_edge_geodesic_smoothstep' and falloff['seed_indices'] == [0]
                assert not falloff['weights_truncated']
                for sample in falloff['weight_samples']:
                    assert math.isclose(sample['weight'],weights[sample['index']],abs_tol=2e-6)
            if symmetry:
                symmetric = edit['symmetry']
                assert symmetric['axis'] == 'X' and symmetric['pairs'] == [[0,4],[1,1]], symmetric
                assert symmetric['policy'] == 'reflect_displacement_preserve_source_asymmetry'
            assert edit['mesh_sha256_before'] != edit['mesh_sha256_after']
            current = await snapshot()
            old, new = before['objects'][name], current['objects'][name]
            for i,(oldpoint,newpoint) in enumerate(zip(old['vertices'],new['vertices'],strict=True)):
                wanted = [v+d*weights.get(i,0) for v,d in zip(oldpoint,displacement(i),strict=True)]
                assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(newpoint,wanted,strict=True))
            assert all(new[k] == v for k,v in old.items() if k not in ('vertices','keys','deformed'))
            for key, spec in old['keys'].items():
                actual = new['keys'][key]
                assert all(actual[k] == v for k,v in spec.items() if k != 'points')
                for i,(a,b) in enumerate(zip(actual['points'],spec['points'],strict=True)):
                    wanted = [v+d*weights.get(i,0) for v,d in zip(b,displacement(i),strict=True)]
                    assert all(math.isclose(x,y,abs_tol=1e-6) for x,y in zip(a,wanted,strict=True))
            if old['keys']:
                for angle in ('0','0.3'):
                    assert abs(old['deformed'][f'{angle}/1'][0][2]-old['deformed'][f'{angle}/0'][0][2]) > .01
                    assert abs(old['deformed'][f'{angle}/2'][0][2]-old['deformed'][f'{angle}/0'][0][2]) > .01
                    for expression in (1,2):
                        for i in range(vertex_count):
                            a,b = f'{angle}/{expression}', f'{angle}/0'
                            original = [x-y for x,y in zip(old['deformed'][a][i],old['deformed'][b][i],strict=True)]
                            actual = [x-y for x,y in zip(new['deformed'][a][i],new['deformed'][b][i],strict=True)]
                            assert all(math.isclose(x,y,abs_tol=2e-6) for x,y in zip(actual,original,strict=True))
            assert current['objects']['SharedA'] == before['objects']['SharedA']
            assert current['objects']['SharedB'] == before['objects']['SharedB']
            assert all(current[k] == v for k,v in before.items() if k != 'objects')
            receipts[name] = edit
        if symmetry:
            previous = current
            direct = await call('mesh_edit',action='move_vertices',name='Static',vertex_indices=[3],
                offset=[.125,0,0],symmetry_axis='X',symmetry_tolerance_m=.00001,
                expected_mesh_sha256=receipts['Static']['mesh_sha256_after'],lease_id=lease)
            assert direct['vertex_edit']['changed_vertices'] == 2 and 'falloff' not in direct['vertex_edit']
            current = await snapshot()
            a,b = previous['objects']['Static'],current['objects']['Static']
            for index,change in ((3,.125),(5,-.125)):
                assert math.isclose(b['vertices'][index][0]-a['vertices'][index][0],change,abs_tol=1e-6)
            assert all(b['vertices'][i] == a['vertices'][i] for i in (0,1,2,4))
            assert all(b[k] == value for k,value in a.items() if k not in ('vertices','deformed'))
            receipts['Static'] = direct['vertex_edit']
        if proportional or symmetry:
            legacy = await call('mesh_edit',action='move_vertices',name='Static',vertex_indices=[5],
                offset=[0,0,.125],expected_mesh_sha256=receipts['Static']['mesh_sha256_after'],lease_id=lease)
            assert legacy['vertex_edit']['changed_vertices'] == 1 and 'falloff' not in legacy['vertex_edit']
            previous = current
            current = await snapshot()
            a,b = previous['objects']['Static'],current['objects']['Static']
            assert all(b[k] == value for k,value in a.items() if k not in ('vertices','deformed'))
            assert b['vertices'][:5] == a['vertices'][:5] and b['vertices'][6:] == a['vertices'][6:]
            assert math.isclose(b['vertices'][5][2]-a['vertices'][5][2],.125,abs_tol=1e-6)
        final_file = f'vertices-{sequence}.blend'
        await call('asset_io',action='open',path='initial.blend',lease_id=lease)
        await call('asset_io',action='open',path=final_file,lease_id=lease)
        assert json.loads((root/'vertex-audit.json').read_text()) == current
        await call('session_control',action='release',lease_id=lease)
        return {'native_vertex_translation':'passed','source_rejections':len(invalid_inputs)-1,'ownership_refusals':1,
                'edited_vertices_per_object':len(weights),'proportional':proportional or symmetry,'symmetric':symmetry,
                'declared_point_mode':'passed',
                'relative_and_absolute_morph_probes':'passed at two rig poses',
                'uvs_pins_colors_weights_and_rig':'preserved','shared_sources':'unchanged',
                'animation_links_and_curves':'preserved','save_reopen':'passed','receipts':receipts}


if __name__ == '__main__':
    main(exercise,Path(__file__).with_name('vertex_edit_fixture.py'))
