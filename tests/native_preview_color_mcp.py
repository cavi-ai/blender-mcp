"""Temporary color controls and precision restoration through real MCP and Blender."""

import hashlib
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main
from PIL import Image, ImageChops


async def exercise(root, env):
    package = Path(__file__).resolve().parents[1] / 'src/cavi_blender_mcp'
    files = ('blender_bridge.py', 'preview_settings.py', 'scene_models.py', 'server.py')
    hashes = {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in files}
    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **args):
            reply = await client.call_tool(tool, args)
            assert not reply.is_error, reply
            return reply.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='preview-color-fixture',
                            expected_project=state['project_id']))['lease_id']
        await call('asset_io', action='save', path='source.blend', lease_id=lease)
        await call('session_control', action='release', lease_id=lease)
        before = await call('scene_info')
        assert before['render_settings']['bit_depth'] == '32'
        assert before['render_settings']['exposure'] == 4
        source = (root / 'source.blend').read_bytes()
        options = {'display_device': 'sRGB', 'view_transform': 'Standard', 'look': 'None',
            'exposure': 0, 'gamma': 1, 'bit_depth': '16', 'use_curve_mapping': False,
            'use_white_balance': False, 'use_compositing': False}
        for name, settings in [('neutral', options), ('bright', {**options, 'exposure': 3})]:
            await call('render_preview', path=name + '.png', resolution=128,
                       names=['Subject'], renderer='eevee', settings=settings)
            assert (root / (name + '.png')).read_bytes()[24] == 16
            assert await call('scene_info') == before
        invalid = await client.call_tool('render_preview', {'path': 'invalid.png', 'resolution': 128,
            'names': ['Subject'], 'renderer': 'eevee', 'settings': {**options, 'look': 'Missing Look'}})
        assert invalid.is_error
        assert not (root / 'invalid.png').exists()
        assert await call('scene_info') == before
        observed = [json.loads(line) for line in (root / 'observed.jsonl').read_text().splitlines()]
        assert len(observed) == 2, observed
        for actual, exposure in zip(observed, (0, 3), strict=True):
            assert actual['exposure'] == exposure and actual['gamma'] == 1
            assert actual['display_device'] == 'sRGB' and actual['view_transform'] == 'Standard'
            assert actual['look'] == 'None' and actual['bit_depth'] == '16'
            assert actual['use_curve_mapping'] is False and actual['use_compositing'] is False
            assert actual['use_white_balance'] in (False, None)
        with Image.open(root / 'neutral.png') as a, Image.open(root / 'bright.png') as b:
            maximum = max(high for low, high in ImageChops.difference(a.convert('RGB'), b.convert('RGB')).getextrema())
        assert maximum > 10, maximum
        assert (root / 'source.blend').read_bytes() == source
        assert hashes == {name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in files}
        return {'png_bit_depth': 16, 'source_exr_bit_depth_restored': 32, 'settings_observed_during_render': True,
                'exposure_pixel_difference': maximum, 'state_restored_after_success_and_failure': True,
                'source_unchanged': True, 'source_sha256': hashes}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('preview_color_fixture.py'))
