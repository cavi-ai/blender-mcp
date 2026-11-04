"""Exercise NLA composition through real MCP stdio and a private native Blender bridge."""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[1]


async def exercise(root, env):
    params = StdioServerParameters(command=sys.executable,
        args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()

        async def call(tool_name, **arguments):
            result = await client.call_tool(tool_name, arguments)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='nla-native-mcp',
            expected_project=state['project_id']))['lease_id']

        async def rig(action, **arguments):
            return await call('rig_edit', action=action, name='Performance', lease_id=lease, **arguments)

        await rig('create', bones=[{'name': 'Root', 'head': [0, 0, -1], 'tail': [0, 0, 0]},
            {'name': 'Spine', 'head': [0, 0, 0], 'tail': [0, 0, 1], 'parent': 'Root'}])
        await call('object_edit', action='create_primitive', name='Skin', kind='sphere', lease_id=lease)
        await rig('bind', names=['Skin'])
        for action, bone, angles in [('Idle', 'Root', [0, 0, 0]), ('Gesture', 'Spine', [0, 45, 0])]:
            await rig('keyframe', action_name=action, keyframes=[
                {'frame': frame, 'poses': [{'bone': bone, 'rotation_degrees': [0, 0, angle]}]}
                for frame, angle in zip([1, 11, 21], angles, strict=True)])
        await rig('nla_push', action_name='Idle', track_name='Base', strip_name='Idle',
            strip_settings={'repeat': 2, 'extrapolation': 'NOTHING'})
        await rig('nla_push', action_name='Gesture', track_name='Gesture', strip_name='Wave',
            strip_settings={'repeat': 2, 'blend_type': 'COMBINE', 'blend_in': 5,
                'blend_out': 5, 'extrapolation': 'NOTHING'})
        inspected = await call('inspect_rig', armature='Performance', meshes=['Skin'])
        assert inspected['nla_tracks'][1]['strips'][0]['strip_settings']['repeat'] == 2, inspected
        changed = await rig('nla_edit', track_name='Gesture', strip_name='Wave',
            strip_settings={'frame_start': 5.5, 'action_frame_start': 3, 'action_frame_end': 19,
                'scale': .5, 'blend_in': 1, 'blend_out': 2})
        assert changed['frame_range'] == [5.5, 21.5], changed
        assert changed['strip_settings']['repeat'] == 2
        await rig('nla_edit', track_name='Gesture', strip_name='Wave',
            strip_settings={'frame_start': 1, 'action_frame_start': 1, 'action_frame_end': 21,
                'scale': 1, 'blend_in': 5, 'blend_out': 5})
        await rig('bake', names=['Skin'], new_name='Performance_Baked', action_name='LayeredPerformance',
            start_frame=1, end_frame=41, frame_step=.1)
        compared = await call('compare_rig_motion', source='Performance', candidate='Performance_Baked',
            meshes=[{'source': 'Skin', 'candidate': 'Performance_Baked_Skin1'}],
            start_frame=1, end_frame=41, max_error_m=.0005, samples=32, space='world', vertex_match='index')
        assert compared['passed'], compared
        await call('asset_io', action='export', path='performance.fbx', names=['Performance_Baked_Skin1'],
            animations=True, baked_animation=True, animation_sample_step=.1, lease_id=lease)
        imported = await call('asset_io', action='import', path='performance.fbx', name='RoundTrip', lease_id=lease)
        assert len(imported['armatures']) == len(imported['skinned_meshes']) == 1, imported
        check = await call('compare_rig_motion', source='Performance', candidate=imported['armatures'][0],
            meshes=[{'source': 'Skin', 'candidate': imported['skinned_meshes'][0]}],
            start_frame=1, end_frame=41, max_error_m=.0005, samples=32, space='world',
            vertex_match='point_set', candidate_frame_offset=1)
        assert check['passed'], check
        await call('asset_io', action='save', path='performance.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'frame_range': changed['frame_range'],
                'bake_max_error_m': compared['max_error_m'], 'fbx_max_error_m': check['max_error_m']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--blender', default=shutil.which('blender'), required=not shutil.which('blender'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary).resolve()
        env = {**os.environ, 'PYTHONPATH': str(REPO/'src'), 'CAVI_BLENDER_WORKSPACE': str(root),
               'CAVI_BLENDER_CONNECTION': str(root/'connection.json')}
        worker = f"""import sys,time
from pathlib import Path
sys.path.insert(0, {str(REPO/'src')!r})
from cavi_blender_mcp import blender_bridge as bridge
bridge.register()
deadline=time.monotonic()+120
try:
    while not Path({str(root/'stop')!r}).exists() and time.monotonic()<deadline:
        bridge.pump()
        time.sleep(.01)
finally:
    bridge.unregister()
"""
        with (root/'blender.log').open('w') as log:
            process = subprocess.Popen([args.blender, '--background', '--factory-startup',
                '--disable-autoexec', '--python-exit-code', '1', '--python-expr', worker],
                env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic()+30
                while not (root/'connection.json').exists():
                    if process.poll() is not None or time.monotonic()>deadline:
                        raise RuntimeError((root/'blender.log').read_text())
                    time.sleep(.05)
                result = asyncio.run(exercise(root, env))
            finally:
                (root/'stop').touch()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            assert process.returncode == 0, (root/'blender.log').read_text()
        print(json.dumps(result))


if __name__ == '__main__':
    main()
