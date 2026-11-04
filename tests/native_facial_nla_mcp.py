"""Compose two facial skins and body motion through MCP, then round-trip the bake."""

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from native_nla_mcp import main


async def exercise(root, env):
    import sys

    params = StdioServerParameters(command=sys.executable, args=['-m', 'cavi_blender_mcp.server'], env=env)
    async with stdio_client(params) as streams, ClientSession(*streams) as client:
        initialized = await client.initialize()

        async def call(tool_name, **arguments):
            result = await client.call_tool(tool_name, arguments)
            assert not result.is_error, result
            return result.structured_content

        state = await call('session_control', action='inspect')
        lease = (await call('session_control', action='claim', owner='facial-performance',
            expected_project=state['project_id']))['lease_id']

        async def rig(action, **kwargs):
            return await call('rig_edit', action=action, name='Rig', lease_id=lease, **kwargs)

        async def face(action, name='Face', **kwargs):
            return await call('rig_edit', action=action, name=name, animation_target='SHAPE_KEYS',
                              lease_id=lease, **kwargs)

        await rig('create', bones=[{'name': 'Head', 'head': [0, 0, -1], 'tail': [0, 0, 1]}])
        await rig('keyframe', action_name='Body', keyframes=[
            {'frame': f, 'poses': [{'bone': 'Head', 'rotation_degrees': [0, 0, a]}]}
            for f, a in [(1, 0), (11, 20), (21, 0)]])
        await rig('nla_push', action_name='Body', track_name='Body', strip_name='Body')
        for skin in ['Face', 'Lids']:
            await call('object_edit', action='create_primitive', name=skin, kind='cube', lease_id=lease)
            await rig('bind', names=[skin])
            for shape, offsets in [('Blink', [[0, 0, 0, -.2]]), ('Smile', [[1, .1, 0, 0]])]:
                action = skin+shape
                await call('object_edit', action='shape_key_add', name=skin, new_name=shape,
                           offsets=offsets, lease_id=lease)
                await call('object_edit', action='shape_key_keyframe', name=skin, new_name=shape,
                    action_name=action, keyframes=[{'frame': f, 'value': v}
                        for f, v in [(1, 0), (6, 1), (11, 0)]], lease_id=lease)
                pushed = await face('nla_push', name=skin, action_name=action,
                    track_name=shape, strip_name=shape, strip_settings={'repeat': 2, 'extrapolation': 'NOTHING'})
                assert pushed['animation_target'] == 'SHAPE_KEYS', pushed
            await face('nla_edit', name=skin, track_name='Smile', strip_name='Smile',
                strip_settings={'frame_start': 3.5, 'scale': .5, 'influence': .5,
                                'use_animated_influence': True, 'blend_type': 'ADD'})
        inspected = await call('inspect_rig', armature='Rig', meshes=['Face', 'Lids'])
        assert len(inspected['nla_tracks']) == 1
        for skin in inspected['meshes']:
            layers = skin['shape_key_animation']
            assert layers['active_action'] is None and len(layers['nla_tracks']) == 2, skin
        await rig('bake', names=['Face', 'Lids'], new_name='Baked', action_name='Performance',
                  start_frame=1, end_frame=21, frame_step=.1)
        pairs = [{'source': skin, 'candidate': 'Baked_Skin'+str(i+1)} for i, skin in enumerate(['Face', 'Lids'])]
        comparison = {'source': 'Rig', 'candidate': 'Baked', 'meshes': pairs, 'start_frame': 1,
                      'end_frame': 21, 'max_error_m': .0005, 'samples': 32, 'space': 'world', 'vertex_match': 'index'}
        baked = await call('compare_rig_motion', **comparison)
        assert baked['passed'], baked
        # Detect the facial surface contribution, independently of body motion.
        await face('nla_edit', track_name='Blink', strip_name='Blink', strip_settings={'mute': True})
        missing_face = await call('compare_rig_motion', **comparison)
        assert not missing_face['passed'] and missing_face['max_error_m'] > .01, missing_face
        await face('nla_edit', track_name='Blink', strip_name='Blink', strip_settings={'mute': False})
        roundtrips = {}
        for extension in ['fbx', 'glb']:
            options = {'animation_sample_step': .1} if extension == 'fbx' else {}
            await call('asset_io', action='export', path='performance.'+extension,
                names=[p['candidate'] for p in pairs], animations=True, baked_animation=True,
                lease_id=lease, **options)
            imported = await call('asset_io', action='import', path='performance.'+extension,
                                  name='Imported'+extension, lease_id=lease)
            assert len(imported['armatures']) == 1 and len(imported['skinned_meshes']) == 2, imported
            names = {item['exported_name']: item['name'] for item in imported['source_objects']}
            assert all(p['candidate'] in names for p in pairs), imported
            meshes = [{'source': p['source'], 'candidate': names[p['candidate']]} for p in pairs]
            compared = await call('compare_rig_motion', **{**comparison, 'candidate': imported['armatures'][0],
                'meshes': meshes, 'vertex_match': 'point_set', 'candidate_frame_offset': 1 if extension == 'fbx' else 0})
            assert compared['passed'], compared
            roundtrips[extension] = compared['max_error_m']
        await call('asset_io', action='save', path='facial-performance.blend', lease_id=lease)
        return {'mcp_version': initialized.server_info.version, 'skins': 2, 'facial_layers_per_skin': 2,
                'bake_max_error_m': baked['max_error_m'], 'roundtrip_max_error_m': roundtrips,
                'muted_face_error_m': missing_face['max_error_m']}


if __name__ == '__main__':
    main(exercise)
