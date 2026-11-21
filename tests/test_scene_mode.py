import unittest

from cavi_blender_mcp.scene_mode import require_scene_mode


class SceneModeTests(unittest.TestCase):
    def test_require_scene_mode_rejects_invalid_shapes(self):
        cases=(
            ({'scope':'source_mesh_vertices','vertices':8},
             'Source vertex pages require a vertex list'),
            ({'vertices':-1},'Named-object vertices require a nonnegative integer count'),
            ({'vertices':True},'Named-object vertices require a nonnegative integer count'),
            ({'scope':'mesh_surface_pick','surface_pick':{}},
             'Surface picks require an explicit hit or miss'),
            ({'scope':'scene_surface_pick','surface_pick':None},
             'Surface picks require an explicit hit or miss'),
            ({'scope':'scene_surface_pick','surface_pick':{'hit':True}},
             'Scene hits require explicit source mapping availability'),
        )
        for value,message in cases:
            with self.subTest(value=value),self.assertRaises(ValueError) as caught:
                require_scene_mode(value)
            self.assertEqual(str(caught.exception),message)
        pick={'hit':True,'source_mapping':{'available':False}}
        for field in ('face_index','triangle_vertices','triangle_loops','uv'):
            with self.subTest(field=field),self.assertRaises(ValueError) as caught:
                require_scene_mode({'scope':'scene_surface_pick','surface_pick':{**pick,field:0}})
            self.assertEqual(str(caught.exception),
                             'Unmapped scene geometry cannot report editable source faces or UVs')

    def test_require_scene_mode_accepts_each_scope(self):
        payloads=(
            {'scope':'source_mesh_vertices','vertices':[{'index':0}]},
            {'scope':'mesh_surface_pick','surface_pick':{'hit':True}},
            {'scope':'scene_surface_pick','surface_pick':{'hit':True,
                                                          'source_mapping':{'available':True}}},
        )
        for payload in payloads:
            with self.subTest(scope=payload['scope']):
                self.assertIs(require_scene_mode(payload),payload)
        self.assertIs(require_scene_mode('plain'),'plain')
