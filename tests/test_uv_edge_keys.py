import unittest


class UVEdgeKeyTests(unittest.TestCase):
    def key(self):
        from cavi_blender_mcp import uv_layout

        self.assertTrue(hasattr(uv_layout,'uv_edge_key'),'Source UV edge matching is not shared')
        return uv_layout.uv_edge_key

    def test_shared_uv_edges_are_orientation_independent_and_exact(self):
        import math

        key=self.key()
        first,second=(2,.125,.25),(7,.375,.5)
        self.assertEqual(key(first,second),key(second,first))
        self.assertNotEqual(key(first,second),key(first,(7,math.nextafter(.375,1),.5)))
        self.assertNotEqual(key(first,second),key(first,(8,.375,.5)))

    def test_nonfinite_uvs_are_rejected(self):
        key=self.key()
        for number in (float('nan'),float('inf'),-float('inf')):
            with self.subTest(number=number),self.assertRaises(ValueError):
                key((0,number,.5),(1,.25,.75))
