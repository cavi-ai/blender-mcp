import importlib.util
import unittest


class FaceRegionTests(unittest.TestCase):
    def component(self):
        self.assertIsNotNone(importlib.util.find_spec('cavi_blender_mcp.face_regions'),
                             'Connected source-face selection is unavailable')
        from cavi_blender_mcp.face_regions import component
        return component

    def test_region_respects_barriers_disconnected_shells_and_nonmanifold_edges(self):
        component=self.component()
        edges=[(0,1),(1,2),(1,3),(3,4),(2,4,5),(5,),(4,4)]
        self.assertEqual(component(0,6,edges,{1,2}),[0,1])
        self.assertEqual(component(0,6,edges,set()),[0,1,2,3,4])
        self.assertEqual(component(5,6,edges,set()),[5])

    def test_seed_requires_a_current_integer_face(self):
        component=self.component()
        for seed in (-1,True,2,1.5):
            with self.subTest(seed=seed),self.assertRaises(ValueError):
                component(seed,2,[(0,1)],set())
