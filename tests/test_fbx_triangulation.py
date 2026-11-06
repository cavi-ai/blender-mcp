"""FBX triangulation is opt-in and reaches the native exporter unchanged."""

import asyncio
import importlib.util
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy  # Load before sys.modules isolation; NumPy extensions cannot be reloaded.

from cavi_blender_mcp import server


class TriangulationSurfaceTests(unittest.TestCase):
    def test_static_animated_uv_and_assembly_exports_forward_opt_in(self):
        for options, operation in [({}, 'export_asset'), ({'animations': True}, 'export_asset'),
                                   ({'uv_layer': 'Atlas'}, 'export_uv_asset'),
                                   ({'assembly': True}, 'export_assembly')]:
            with self.subTest(options=options), patch.object(server, 'call', return_value={}) as call:
                asyncio.run(server.asset_io('export', 'asset.fbx', names=['Skin'],
                                            triangulate=True, **options))
                self.assertEqual(call.call_args.args, (operation,))
                self.assertIs(call.call_args.kwargs['triangulate'], True)

    def test_default_static_export_retains_legacy_operation_and_arguments(self):
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.asset_io('export', 'asset.fbx', names=['Skin']))
        self.assertEqual(call.call_args.args, ('export_mesh',))
        self.assertNotIn('triangulate', call.call_args.kwargs)
        with patch.object(server, 'call', return_value={}) as call:
            asyncio.run(server.asset_io('export', 'asset.glb', names=['Skin'], assembly=True))
        self.assertEqual(call.call_args.args, ('export_assembly',))
        self.assertNotIn('triangulate', call.call_args.kwargs)

    def test_non_fbx_other_actions_and_bake_pairs_reject_before_dispatch(self):
        with patch.object(server, 'call', return_value={}) as call:
            for action, path, options in [
                ('export', 'asset.glb', {'names': ['Skin']}),
                ('export', 'asset.usdc', {'names': ['Skin']}),
                ('save', 'asset.blend', {}), ('import', 'asset.fbx', {'name': 'Loaded'}),
                ('export', 'pair.fbx', {'bake_pair': server.BakePair(low=['Low'], high=['High'])}),
            ]:
                with self.subTest(action=action, path=path), self.assertRaises(ValueError):
                    asyncio.run(server.asset_io(action, path, triangulate=True, **options))
        call.assert_not_called()

    def test_tool_schema_rejects_non_boolean_opt_in(self):
        with patch.object(server, 'call', return_value={}) as call, \
                self.assertRaisesRegex(Exception, 'validation error'):
            asyncio.run(server.mcp.call_tool('asset_io', {
                'action': 'export', 'path': 'asset.fbx', 'names': ['Skin'], 'triangulate': 'true'}))
        call.assert_not_called()


class ExporterForwardingTests(unittest.TestCase):
    def setUp(self):
        self.operator = Mock(return_value={'FINISHED'})
        self.bpy = SimpleNamespace(ops=SimpleNamespace(export_scene=SimpleNamespace(fbx=self.operator)))
        self.output = Mock(side_effect=lambda path, formats: nullcontext(
            SimpleNamespace(stat=lambda: SimpleNamespace(st_size=1))))
        self.obj = SimpleNamespace(name='Skin', data=SimpleNamespace(vertices=[None],
            polygons=[SimpleNamespace(vertices=[0, 1, 2, 3, 4])]),
            modifiers=[SimpleNamespace(type='ARMATURE')])
        modules = {'bpy': self.bpy, 'numpy': numpy,
            'cavi_blender_mcp.blender_bridge': SimpleNamespace(obj=lambda *a, **k: self.obj,
                output_file=self.output, selected=lambda *a: nullcontext(), with_empties=lambda x: x),
            'cavi_blender_mcp.blender_export_uv': SimpleNamespace(promote=lambda *a: nullcontext(None)),
            'cavi_blender_mcp.export_instances': SimpleNamespace(instance_meshes=lambda *a: nullcontext())}
        self.enterContext(patch.dict(sys.modules, modules))
        source = Path(server.__file__).with_name('blender_export.py')
        spec = importlib.util.spec_from_file_location('cavi_blender_mcp._fbx_test', source)
        self.native = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.native)

    def test_operator_default_is_false_and_opt_in_is_true(self):
        self.native.fbx(Path('default.fbx'), 'unity')
        self.assertIs(self.operator.call_args.kwargs['use_triangles'], False)
        self.native.fbx(Path('triangles.fbx'), 'unity', triangulate=True)
        self.assertIs(self.operator.call_args.kwargs['use_triangles'], True)
        self.assertTrue(self.operator.call_args.kwargs['use_tspace'])

    def test_writer_forwards_and_refuses_other_formats_before_export(self):
        self.native.write(Path('asset.fbx'), [], [], 'unity', False, False, triangulate=True)
        self.assertIs(self.operator.call_args.kwargs['use_triangles'], True)
        self.operator.reset_mock()
        for suffix in ('.glb', '.usdc'):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, 'FBX'):
                self.native.write(Path('asset' + suffix), [], [], 'unity', False, False,
                                  triangulate=True)
        self.operator.assert_not_called()

    def test_static_and_animated_kernel_paths_forward_to_writer(self):
        rig = SimpleNamespace(name='Rig', data=SimpleNamespace(bones=[]))
        action = SimpleNamespace(name='Stride', frame_range=[1, 49])
        with patch.object(self.native, 'write', return_value={}) as write, \
                patch.object(self.native, 'animation_targets', return_value=([rig], [])), \
                patch.object(self.native, 'actions_for', return_value=[action]):
            for animated in (False, True):
                with self.subTest(animated=animated):
                    self.native.export_asset({'path': 'asset.fbx', 'names': ['Skin'],
                                              'animations': animated, 'triangulate': True})
                    self.assertIs(write.call_args.kwargs['triangulate'], True)

    def test_kernel_refuses_wrong_format_or_type_before_output_allocation(self):
        for params in ({'path': 'asset.glb', 'triangulate': True},
                       {'path': 'asset.fbx', 'triangulate': 'true'}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                self.native.export_asset({'names': ['Skin'], **params})
        self.output.assert_not_called()
