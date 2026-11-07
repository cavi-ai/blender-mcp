import unittest

from cavi_blender_mcp.contracts import SceneInfo


class ScenePickContractTests(unittest.TestCase):
    def test_scene_picks_require_explicit_hit_and_source_mapping(self):
        for pick in ({},{'hit':'yes'},{'hit':True},{'hit':True,'source_mapping':{'available':'yes'}}):
            with self.subTest(pick=pick),self.assertRaises(ValueError):
                SceneInfo.model_validate({'scope':'scene_surface_pick','surface_pick':pick})

    def test_generated_hits_cannot_be_reported_as_editable_source_faces(self):
        pick={'hit':True,'source_mapping':{'available':False}}
        SceneInfo.model_validate({'scope':'scene_surface_pick','surface_pick':pick})
        for field in ('face_index','triangle_vertices','triangle_loops','uv'):
            with self.subTest(field=field),self.assertRaises(ValueError):
                SceneInfo.model_validate({'scope':'scene_surface_pick','surface_pick':{**pick,field:0}})
