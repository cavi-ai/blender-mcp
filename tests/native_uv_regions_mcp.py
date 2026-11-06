"""One private native case for selected-face UVs, protected data and rectangular pixel gutters."""
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

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='uv-region-case',
            expected_project=state['project_id']))['lease_id']
        page = await call('scene_info', name='Panel', faces=True)
        top = [f['index'] for f in page['faces'] if f['normal_local'][2] > .9]
        await call('object_edit', action='make_single_user', name='Panel', lease_id=lease)
        edited = await call('mesh_edit', action='extrude_faces', name='Panel', face_indices=top,
            offset=[0,0,.4], expected_mesh_sha256=page['mesh_sha256'], lease_id=lease)
        sides = edited['extrusion']['side_faces']
        digest = edited['extrusion']['mesh_sha256_after']
        await call('asset_io', action='save', path='before-uv.blend', lease_id=lease)

        async def audit():
            await call('inspect_mesh_quality', names=['Panel'], checks=['topology'],
                       texture_resolution=[2048,1024], uv_layer='BakeAtlas')
            return json.loads((root/'uv-audit.json').read_text())

        before = await audit()
        spec = {'bounds':[.55,.55,.98,.98], 'texture_resolution':[2048,1024], 'margin_px':8}
        args = {'action':'unwrap_faces','name':'Panel','face_indices':sides,'uv_layer':'BakeAtlas',
                'uv_region':spec,'expected_mesh_sha256':digest,'lease_id':lease}
        for invalid in ({'expected_mesh_sha256':'0'*64}, {'uv_layer':'Missing'},
                        {'uv_region':{**spec,'bounds':[0,0,.5,.5]}}):
            rejected = await client.call_tool('mesh_edit', {**args, **invalid})
            assert rejected.is_error, rejected
            assert (rejected.structured_content or {}).get('error',{}).get('outcome') == 'rejected', rejected
            assert (await audit())['uvs'] == before['uvs']
            assert not (await call('scene_info',limit=1))['source_state']['dirty']
        result = await call('mesh_edit', **args)
        report = result['face_unwrap']
        assert report['quality']['passed'] and report['reservation']['checked']
        assert report['quality']['padding_pairs_below_requested'] == 0
        assert report['quality']['minimum_region_border_pixels'] >= 8
        after = await audit()
        target_loops = {i for face in sides for i in before['loops'][str(face)]}
        assert any(before['uvs']['BakeAtlas'][i] != after['uvs']['BakeAtlas'][i] for i in target_loops)
        assert all(before['uvs']['BakeAtlas'][i] == after['uvs']['BakeAtlas'][i]
                   for i in range(len(before['uvs']['BakeAtlas'])) if i not in target_loops)
        for key in ('geometry','float_colors','materials','selected','active','mode','transform','pins'):
            assert after[key] == before[key], key
        assert after['uvs']['ArtistUV'] == before['uvs']['ArtistUV']
        assert any(after['pins']['BakeAtlas'])
        tiled = await call('mesh_edit', **{**args, 'uv_region':{**spec, 'bounds':[1.1,.1,1.8,.8]}})
        assert tiled['face_unwrap']['quality']['passed']
        tiled_after = await audit()
        assert all(tiled_after['uvs']['BakeAtlas'][i][0] > 1 for i in target_loops)
        assert all(before['uvs']['BakeAtlas'][i] == tiled_after['uvs']['BakeAtlas'][i]
                   for i in range(len(before['uvs']['BakeAtlas'])) if i not in target_loops)
        assert tiled_after['uvs']['ArtistUV'] == before['uvs']['ArtistUV']
        for key in ('geometry','float_colors','materials','selected','active','mode','transform','pins'):
            assert tiled_after[key] == before[key], key
        after = tiled_after
        assert not list(root.glob('.cavi-uv-*'))
        await call('asset_io', action='save', path='uv-finished.blend', lease_id=lease)
        await call('asset_io', action='open', path='initial.blend', lease_id=lease)
        await call('asset_io', action='open', path='uv-finished.blend', lease_id=lease)
        reopened = await audit()
        assert reopened['uvs'] == after['uvs']
        await call('session_control', action='release', lease_id=lease)
        return {'native_selected_uv_unwrap':'passed','texture_resolution':[2048,1024],
            'padding':report['quality'], 'protected_uvs_colors_materials_geometry_preserved':True,
            'host_context_preserved':True,'saved_project_roundtrip':'passed','worker_cleaned':True,
            'explicit_udim_destination':'passed','unselected_pins_preserved':True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('uv_regions_fixture.py'))
