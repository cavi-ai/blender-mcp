"""One MCP case: source-point translation retains morphs, skin, UVs and context."""
import json
import math
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env, parameters=None):
    params = parameters or StdioServerParameters(command=sys.executable,
        args=['-m','cavi_blender_mcp.server'],env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            result = await client.call_tool(tool,args)
            assert not result.is_error, result
            return result.structured_content

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
        pages = [await call('scene_info',name='TileGrid',vertices=True,limit=3,offset=i) for i in (0,3)]
        assert pages[0]['mesh_sha256'] == pages[1]['mesh_sha256']
        assert [v['index'] for p in pages for v in p['vertices']] == list(range(6))
        selected = [v['index'] for p in pages for v in p['vertices']
                    if v['position_local'][1] == -1 and v['position_local'][0] <= 0]
        assert selected == [0,1]
        empty = await call('scene_info',name='TileGrid',vertices=True,offset=100)
        assert empty['vertices'] == [] and empty['total'] == 6
        assert await snapshot() == before
        args = {'action':'move_vertices','name':'TileGrid','vertex_indices':selected,
                'offset':[.25,.125,.5],'expected_mesh_sha256':pages[0]['mesh_sha256'],'lease_id':lease}
        for invalid in ({'vertex_indices':[6]}, {'vertex_indices':[0,0]}, {'offset':[0,0,0]},
                        {'expected_mesh_sha256':'0'*64}, {'name':'SharedA'}, {'lease_id':'other'}):
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
            assert edit['changed_vertices'] == 2 and edit['max_shape_delta_error_local'] < 1e-6, edit
            assert edit['mesh_sha256_before'] != edit['mesh_sha256_after']
            current = await snapshot()
            old, new = before['objects'][name], current['objects'][name]
            for i,(oldpoint,newpoint) in enumerate(zip(old['vertices'],new['vertices'],strict=True)):
                wanted = [v+d for v,d in zip(oldpoint,[.25,.125,.5],strict=True)] if i in selected else oldpoint
                assert all(math.isclose(a,b,abs_tol=1e-6) for a,b in zip(newpoint,wanted,strict=True))
            assert all(new[k] == v for k,v in old.items() if k not in ('vertices','keys','deformed'))
            for key, spec in old['keys'].items():
                actual = new['keys'][key]
                assert all(actual[k] == v for k,v in spec.items() if k != 'points')
                for i,(a,b) in enumerate(zip(actual['points'],spec['points'],strict=True)):
                    wanted = [v+d for v,d in zip(b,[.25,.125,.5],strict=True)] if i in selected else b
                    assert all(math.isclose(x,y,abs_tol=1e-6) for x,y in zip(a,wanted,strict=True))
            if old['keys']:
                for angle in ('0','0.3'):
                    assert abs(old['deformed'][f'{angle}/1'][0][2]-old['deformed'][f'{angle}/0'][0][2]) > .01
                    assert abs(old['deformed'][f'{angle}/2'][0][2]-old['deformed'][f'{angle}/0'][0][2]) > .01
                    for expression in (1,2):
                        for i in range(6):
                            a,b = f'{angle}/{expression}', f'{angle}/0'
                            original = [x-y for x,y in zip(old['deformed'][a][i],old['deformed'][b][i],strict=True)]
                            actual = [x-y for x,y in zip(new['deformed'][a][i],new['deformed'][b][i],strict=True)]
                            assert all(math.isclose(x,y,abs_tol=2e-6) for x,y in zip(actual,original,strict=True))
            assert current['objects']['SharedA'] == before['objects']['SharedA']
            assert current['objects']['SharedB'] == before['objects']['SharedB']
            assert all(current[k] == v for k,v in before.items() if k != 'objects')
            receipts[name] = edit
        final_file = f'vertices-{sequence}.blend'
        await call('asset_io',action='open',path='initial.blend',lease_id=lease)
        await call('asset_io',action='open',path=final_file,lease_id=lease)
        assert json.loads((root/'vertex-audit.json').read_text()) == current
        await call('session_control',action='release',lease_id=lease)
        return {'native_vertex_translation':'passed','source_rejections':5,'ownership_refusals':1,
                'edited_vertices_per_object':2,
                'relative_and_absolute_morph_probes':'passed at two rig poses',
                'uvs_pins_colors_weights_and_rig':'preserved','shared_sources':'unchanged',
                'animation_links_and_curves':'preserved','save_reopen':'passed','receipts':receipts}


if __name__ == '__main__':
    main(exercise,Path(__file__).with_name('vertex_edit_fixture.py'))
