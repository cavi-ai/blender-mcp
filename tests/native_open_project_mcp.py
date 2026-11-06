"""Project switching through real stdio MCP and CLI on a private headless Blender."""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        await client.initialize()

        async def call(tool, **arguments):
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result
            return result.structured_content

        async def reject(**arguments):
            result = await client.call_tool('asset_io', {'action': 'open',
                'path': 'target.blend', 'lease_id': lease, **arguments})
            assert result.is_error, result

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='saved-project-case',
            expected_project=state['project_id']))['lease_id']
        await call('asset_io', action='export', names=['SourceProp'], path='source.glb', lease_id=lease)
        assert not (await call('scene_info', limit=1))['source_state']['dirty']
        await reject(lease_id='wrong')
        await reject(expected_sha256='0' * 64)
        assert (await call('session_control', action='inspect'))['project_id'] == state['project_id']
        digest = hashlib.sha256((root / 'target.blend').read_bytes()).hexdigest()
        opened = await call('asset_io', action='open', path='target.blend',
            expected_sha256=digest, lease_id=lease)
        assert opened['opened'] and opened['sha256'] == digest
        switched = await call('session_control', action='inspect')
        assert switched['project_id'] != state['project_id']
        assert switched['project_id'] == switched['claimed_project_id'] == opened['project_id']
        assert switched['active']
        assert (await call('scene_info', name='TargetProp'))['name'] == 'TargetProp'
        source = (await call('scene_info', limit=1))['source_state']
        assert source['saved_source']['sha256'] == digest and not source['dirty']
        assert not (root / 'autorun-ran').exists()
        same = await call('asset_io', action='open', path='target.blend', lease_id=lease)
        assert not same['opened'] and same['project_id'] == opened['project_id']
        # A replacement on disk must not relabel or discard the loaded source.
        path = root / 'target.blend'
        raw = path.read_bytes()
        path.write_bytes(raw + b'external replacement')
        try:
            await reject(path='source.blend')
            assert (await call('scene_info', limit=1))['source_state'] == source
        finally:
            path.write_bytes(raw)
        process = await asyncio.create_subprocess_exec(sys.executable, '-m',
            'cavi_blender_mcp.cli', 'runtime', 'open', '--project', 'source.blend',
            '--lease-id', lease, env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), 30)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        assert process.returncode == 0, (stdout, stderr)
        cli = json.loads(stdout)
        assert cli['opened']
        # This handler writes RNA directly; source tracking must preserve that edit.
        await call('object_edit', action='transform', name='SourceProp', location=[1, 2, 3],
            lease_id=lease)
        assert (await call('scene_info', limit=1))['source_state']['dirty']
        await reject()
        assert (await call('scene_info', name='SourceProp'))['location'] == [1., 2., 3.]
        await call('asset_io', action='save', path='edited-source.blend', lease_id=lease)
        assert not (await call('scene_info', limit=1))['source_state']['dirty']
        await call('asset_io', action='open', path='target.blend', lease_id=lease)
        final = await call('session_control', action='renew', lease_id=lease)
        assert final['project_id'] == final['claimed_project_id']
        await call('session_control', action='release', lease_id=lease)
        return {'headless_project_switch_mcp': 'passed', 'cli_switch': 'passed',
            'lease_follows_successful_load': True, 'bridge_survives_load': True,
            'dirty_edit_and_external_replacement_preserved': True,
            'saved_source_sha256_verified': True, 'autorun_disabled': True}


if __name__ == '__main__':
    main(exercise, Path(__file__).with_name('open_project_fixture.py'))
