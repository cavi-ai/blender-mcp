"""Batched spatial distances equal the scalar functions; batched proofs keep their contract."""
import random
import unittest

from cavi_blender_mcp import spatial_query as sq

TRIANGLE = ((0., 0., 0.), (1., 0., 0.), (0., 1., 0.))
EDGE_CASES = {
    'coplanar_contained': ((.2, .2, 0.), (.4, .2, 0.), (.2, .4, 0.)),
    'coplanar_separated': ((1., 1., 0.), (2., 1., 0.), (1., 2., 0.)),
    'coplanar_opposite_winding': ((.2, .2, 0.), (.2, .4, 0.), (.4, .2, 0.)),
    'coplanar_shared_edge': ((1., 0., 0.), (0., 1., 0.), (1., 1., 0.)),
    'shared_edge_folded': ((1., 0., 0.), (0., 1., 0.), (0., 0., 1.)),
    'touching_vertex': ((1., 0., 0.), (2., 0., 1.), (2., 1., 0.)),
    'vertex_on_face': ((.25, .25, 0.), (.25, .25, 1.), (.5, .25, 1.)),
    'piercing': ((.25, .25, -1.), (.25, .25, 1.), (.25, .5, 1.)),
    'parallel_offset': ((0., 0., .5), (1., 0., .5), (0., 1., .5)),
    'parallel_edges': ((.2, -.3, .2), (.8, -.3, .2), (.5, -.3, 1.)),
    'crossed_edges': ((.5, -.5, .1), (.5, .5, .1), (2., 0., 3.)),
    'collinear_degenerate': ((0., 0., 1.), (1., 0., 1.), (2., 0., 1.)),
    'collinear_piercing': ((.2, .2, -1.), (.2, .2, 0.), (.2, .2, 1.)),
    'point_degenerate': ((.2, .2, .5), (.2, .2, .5), (.2, .2, .5)),
    'far_apart': ((1e20, 0., 0.), (1e20 + 1., 0., 0.), (1e20, 1., 0.)),
    'skinny': ((.6, 1e-9, 1e-3), (.8, 2e-9, 1e-3), (.8, 4e-9, 1e-3)),
    'tiny_gap': ((.1, .1, 1e-7), (.2, .1, 1e-7), (.1, .2, 1e-7)),
}
LARGE = (1e6, -2e6, 1e6)


def moved(triangle, offset):
    return tuple(tuple(p[i] + offset[i] for i in range(3)) for p in triangle)


def random_triangle(rng, scale=1., offset=(0., 0., 0.)):
    return tuple(tuple(offset[i] + rng.uniform(-scale, scale) for i in range(3))
                 for _ in range(3))


def soup(seed, count, origin, edge=.15):
    rng = random.Random(seed)
    result = []
    for _ in range(count):
        centre = [origin[i] + rng.uniform(0, 1) for i in range(3)]
        result.append(tuple(tuple(c + rng.uniform(-edge, edge) for c in centre)
                            for _ in range(3)))
    return result


def brute_force(subjects, context):
    return min(sq.triangle_distance(a, b) for a in subjects for b in context)


class SpatialBatchTests(unittest.TestCase):
    def assertMatches(self, got, wanted):
        self.assertEqual(len(got), len(wanted))
        for index, (value, expected) in enumerate(zip(got, wanted, strict=True)):
            with self.subTest(index=index, expected=expected):
                if expected == 0:
                    self.assertEqual(value, 0)
                else:
                    self.assertLessEqual(abs(value - expected), 1e-12 * expected)

    def pairs(self):
        rng = random.Random(7)
        pairs = []
        for spread in (0., .5, 1.5, 4.):
            for _ in range(150):
                a = random_triangle(rng)
                pairs.append((a, random_triangle(rng, offset=[rng.uniform(-spread, spread)
                                                                for _ in range(3)])))
        for _ in range(100):
            a = random_triangle(rng)
            pairs.append((a, tuple(tuple(v + rng.uniform(-1e-3, 1e-3) for v in p) for p in a)))
        for name, other in EDGE_CASES.items():
            pairs.append((TRIANGLE, other))
            pairs.append((other, TRIANGLE))
            if name != 'far_apart':
                pairs.append((moved(TRIANGLE, LARGE), moved(other, LARGE)))
        pairs.append((((0, 0, 0), (3, 0, 0), (0, 3, 0)), ((.75, .75, -1), (.75, .75, 1),
                                                         (.75, 1.25, 1))))
        return pairs

    def test_triangle_distances_match_scalar_on_seeded_and_edge_case_pairs(self):
        pairs = self.pairs()
        wanted = [sq.triangle_distance(a, b) for a, b in pairs]
        got = sq.triangle_distances([a for a, _ in pairs], [b for _, b in pairs])
        self.assertEqual(got.shape, (len(pairs),))
        self.assertMatches(got.tolist(), wanted)
        self.assertGreater(wanted.count(0.), 50)
        self.assertGreater(len(wanted) - wanted.count(0.), 300)

    def test_point_triangle_distances_match_scalar(self):
        rng = random.Random(11)
        points, triangles = [], []
        for _ in range(500):
            points.append(tuple(rng.uniform(-2, 2) for _ in range(3)))
            triangles.append(random_triangle(rng))
        probes = [(.2, .2, .5), (.2, .2, 0.), (.5, .5, 0.), (.5, .5, .3), (1., 0., 0.),
                  (2., -1., .5), (-1., -1., -1.), (.3, -.2, 0.)]
        for triangle in (TRIANGLE, EDGE_CASES['collinear_degenerate'],
                         EDGE_CASES['point_degenerate'], EDGE_CASES['skinny']):
            for point in probes:
                points.append(point)
                triangles.append(triangle)
                points.append(tuple(point[i] + LARGE[i] for i in range(3)))
                triangles.append(moved(triangle, LARGE))
        wanted = [sq.point_triangle_distance(p, t) for p, t in zip(points, triangles, strict=True)]
        got = sq.point_triangle_distances(points, triangles)
        self.assertEqual(got.shape, (len(points),))
        self.assertMatches(got.tolist(), wanted)

    def test_batches_reject_mismatched_shapes(self):
        with self.assertRaises(ValueError):
            sq.triangle_distances([TRIANGLE, TRIANGLE], [TRIANGLE])
        with self.assertRaises(ValueError):
            sq.point_triangle_distances([(0., 0., 0.)], [TRIANGLE[:2]])
        self.assertEqual(sq.triangle_distances([], []).shape, (0,))

    def test_proof_keeps_exact_three_axis_distance(self):
        left = ((0., 0., 0.), (-1., 0., 0.), (0., -1., 0.))
        right = ((6., 3., 2.), (7., 3., 2.), (6., 4., 2.))
        # The closest vertices differ by (6, 3, 2), with a norm of exactly 7.
        sampled_upper = float(sq.point_triangle_distances([left[0]], [right])[0])
        for upper in (sampled_upper, 8.):
            with self.subTest(upper=upper):
                proof = sq.prove_distance([left], [right], upper, budget=1)
                self.assertTrue(proof['proven'])
                self.assertEqual(proof['lower_m'], 7.)
                self.assertEqual(proof['upper_m'], 7.)
        self.assertEqual(sampled_upper, 7.)

    def test_larger_budget_preserves_completed_proof(self):
        subjects = [
            ((-7, 3, 4), (-2, -5, -6), (-3, 5, -2)),
            ((-2, -3, 5), (-5, -1, -5), (-1, -1, 1)),
            ((-4, 1, 0), (-4, 0, 2), (-4, -5, -3)),
        ]
        context = [
            ((7, 1, -1), (3, -1, 0), (0, 3, 3)),
            ((5, 1, 1), (0, -3, -4), (7, -5, -6)),
            ((5, 0, -2), (0, 4, 2), (6, -3, 0)),
        ]
        exact = brute_force(subjects, context)
        for budget in range(6, 16):
            with self.subTest(budget=budget):
                proof = sq.prove_distance(subjects, context, upper=7.0710678118654755,
                                          budget=budget)
                self.assertLessEqual(proof['tests'], budget)
                self.assertTrue(proof['proven'], proof)
                self.assertAlmostEqual(proof['lower_m'], exact, places=14)
                self.assertAlmostEqual(proof['upper_m'], exact, places=14)

    def test_finished_proofs_equal_the_brute_force_minimum(self):
        cases = {
            'separated': (soup(1, 48, (0., 0., 0.)), soup(2, 48, (1.2, 0., 0.))),
            'interleaved': (soup(3, 48, (0., 0., 0.), .03), soup(4, 48, (.05, 0., 0.), .03)),
            'touching': (soup(5, 40, (0., 0., 0.)), soup(6, 40, (.9, .3, 0.))),
            'large': ([moved(t, LARGE) for t in soup(7, 40, (0., 0., 0.))],
                      [moved(t, LARGE) for t in soup(8, 40, (1.1, 0., 0.))]),
        }
        for name, (subjects, context) in cases.items():
            with self.subTest(case=name):
                exact = brute_force(subjects, context)
                proof = sq.prove_distance(subjects, context, 10., 1000000)
                self.assertTrue(proof['proven'])
                self.assertEqual(proof['lower_m'], proof['upper_m'])
                self.assertLessEqual(proof['tests'], 1000000)
                self.assertMatches([proof['upper_m']], [exact])

    def test_exhausted_proofs_bracket_the_brute_force_minimum(self):
        subjects, context = soup(9, 48, (0., 0., 0.)), soup(10, 48, (1.05, 0., 0.))
        exact = brute_force(subjects, context)
        self.assertGreater(exact, 0)
        unfinished = 0
        for budget in (1, 5, 20, 60, 200, 600):
            with self.subTest(budget=budget):
                proof = sq.prove_distance(subjects, context, 10., budget)
                self.assertLessEqual(proof['tests'], budget)
                self.assertLessEqual(proof['lower_m'], exact)
                self.assertGreaterEqual(proof['upper_m'], exact * (1 - 1e-12))
                if not proof['proven']:
                    unfinished += 1
                    self.assertLess(proof['lower_m'], proof['upper_m'])
        self.assertGreater(unfinished, 2)


if __name__ == '__main__':
    unittest.main()
