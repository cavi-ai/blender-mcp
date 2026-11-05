"""Real MCP UDIM binding, per-tile receipts and packed material-library delivery."""

import hashlib
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
            reply = await client.call_tool(tool, arguments)
            assert not reply.is_error, reply
            return reply.structured_content
        common = {'material_name': 'ArtistFinish', 'group_path': ['Finish Controls', 'Inner Layer']}
        async def inspect(node='Pattern', **options):
            return await call('assign_material', action='inspect', node=node, **(common | options))
        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='udim-check',
            expected_project=state['project_id']))['lease_id']
        sibling = await inspect('Other Pattern')
        initial = await inspect()
        async def bind(path='glaze.<UDIM>.exr', tiles=None, **options):
            spec = {'path': path, 'color_space': 'Non-Color', **options}
            if tiles is not None:
                spec['tiles'] = tiles
            return await call('assign_material', action='set_image', node='Pattern', image=spec, lease_id=lease, **common)
        result = await bind(tiles=[1011,1002,1001])
        assert result['managed_materials_detached'] == ['ManagedA', 'ManagedB']
        assert result['links'] == initial['links']
        assert [t['tile'] for t in result['nodes'][0]['image']['tiles']] == [1001,1002,1011]
        assert [t['size'] for t in result['nodes'][0]['image']['tiles']] == [[2,2],[4,2],[2,4]]
        def verify(receipt):
            source = receipt['image_source']
            assert source['tile_count'] == len(source['tiles'])
            for tile in source['tiles']:
                payload = (root/tile['path']).read_bytes()
                assert tile['sha256'] == hashlib.sha256(payload).hexdigest()
                assert tile['bytes'] == len(payload)
            packed = receipt['nodes'][0]['image']['packed_tiles']
            assert [(p['tile'],p['sha256']) for p in packed] == [(p['tile'],p['sha256']) for p in source['tiles']]
        verify(result)
        assert not (await bind(tiles=[1001,1002,1011]))['changed_image']
        offset = await bind('offset.<UDIM>.exr', [1002,1011])
        verify(offset)
        assert offset['image_source']['tile_count'] == 2
        png = await bind('glaze.<UDIM>.png', [1001,1002,1011])
        verify(png)
        assert all((root/t['path']).read_bytes()[24] == 16 for t in png['image_source']['tiles'])
        single = await bind('finish.png')
        assert single['nodes'][0]['image']['source'] == 'FILE'
        assert single['image_source']['sha256'] == hashlib.sha256((root/'finish.png').read_bytes()).hexdigest()
        result = await bind(tiles=[1001,1002,1011])
        previous = result['image_source']['manifest_sha256']
        (root/'glaze.1002.exr').write_bytes((root/'glaze.1011.exr').read_bytes())
        revised = await bind(tiles=[1001,1002,1011])
        assert revised['changed_image'] and revised['image_source']['manifest_sha256'] != previous
        verify(revised)
        revised = await bind('alias.<UDIM>.exr', [1001,1002,1011])
        verify(revised)
        assert all(t['path'].startswith('alias.') for t in revised['image_source']['tiles'])
        baseline = await inspect()
        for path, tiles, extra in [('glaze.<UDIM>.exr',[1001,1001],{}),
                ('glaze.<UDIM>.exr',[1001,1005],{}), ('glaze.exr',[1001],{}),
                ('broken.<UDIM>.exr',[1001,1002],{}), ('escape.<UDIM>.exr',[1001],{}),
                ('glaze.<UDIM>.exr',[1001,1002],{'color_space':'not-an-OCIO-space'})]:
            reply = await client.call_tool('assign_material', {'action':'set_image', 'node':'Pattern',
                'image':{'path':path,'tiles':tiles,'color_space':'Non-Color',**extra},'lease_id':lease,**common})
            assert reply.is_error, path
            assert await inspect() == baseline, path
        unowned = await client.call_tool('assign_material', {'action':'set_image','node':'Pattern',
            'image':{'path':'glaze.<UDIM>.exr','tiles':[1001,1002,1011],'color_space':'Non-Color'},**common})
        assert unowned.is_error and await inspect() == baseline
        assert await inspect('Other Pattern') == sibling
        saved = await call('asset_io', action='save', path='udim-material.blend', lease_id=lease)
        for tile in revised['image_source']['tiles']:
            source = root/tile['path']
            resolved = source.resolve()
            source.unlink()
            if resolved != source:
                resolved.unlink()
        state = await call('session_control', action='inspect')
        if state['active']:
            await call('session_control', action='release', lease_id=lease)
        lease = (await call('session_control', action='claim', owner='udim-check',
            expected_project=state['project_id']))['lease_id']
        await call('asset_io', action='save', path='udim-consumer-base.blend', lease_id=lease)
        state = await call('session_control', action='inspect')
        if state['active']:
            await call('session_control', action='release', lease_id=lease)
        lease = (await call('session_control', action='claim', owner='udim-check',
            expected_project=state['project_id']))['lease_id']
        library = await call('asset_library', action='inspect', path='udim-material.blend', kind='materials')
        loaded = await call('asset_library', action='append', path='udim-material.blend', kind='materials',
            names=['ArtistFinish'], expected_sha256=library['sha256'], lease_id=lease)
        copy = await inspect(material_name=loaded['roots'][0]['name'])
        hashes = [(p['tile'],p['sha256']) for p in copy['nodes'][0]['image']['packed_tiles']]
        assert hashes == [(p['tile'],p['sha256']) for p in revised['image_source']['tiles']]
        assert any(len(i.get('files',[])) == 3 for i in loaded['images'])
        await call('asset_io', action='save', path='udim-consumer.blend', lease_id=lease)
        catalog = await client.list_tools()
        assert len(catalog.tools) == 20
        return {'mcp_version':initialized.server_info.version, 'tool_count':len(catalog.tools),
            'tile_numbers':[1001,1002,1011], 'png_source_bit_depth':16, 'float_exr_packed':True,
            'missing_1001_supported':True, 'undeclared_neighbor_excluded':True,
            'unchanged_set_reused':True, 'changed_tile_refreshes_manifest':True,
            'invalid_edits_preserve_binding':True, 'single_file_interop':True, 'logical_tile_paths_preserved':True, 'unowned_edits_rejected':True,
            'portable_append_without_source_files':True, 'saved_blend_bytes':saved['bytes'],
            'tiles':revised['image_source']['tiles']}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('shader_udim_fixture.py'))
