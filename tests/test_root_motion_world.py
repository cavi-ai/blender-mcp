import importlib
import math
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

with patch.dict(sys.modules, {'bpy': SimpleNamespace()}):
    rig_module = importlib.import_module('cavi_blender_mcp.blender_rig')


class Vec:
    def __init__(self, values):
        self.v = np.asarray(values, dtype=float)
    def copy(self):
        return Vec(self.v.copy())
    def __sub__(self, other):
        return Vec(self.v - other.v)
    def __iter__(self):
        return iter(self.v.tolist())
    def __mul__(self, scalar):
        return Vec(self.v * scalar)
    @property
    def x(self): return float(self.v[0])
    @property
    def y(self): return float(self.v[1])
    @property
    def z(self): return float(self.v[2])
    @property
    def length(self): return float(np.linalg.norm(self.v))


class Matrix:
    def __init__(self, matrix): self.matrix = np.asarray(matrix)
    def __iter__(self): return iter(self.matrix.tolist())
    def __matmul__(self, point):
        return Vec((self.matrix @ np.append(point.v, 1))[:3])


def pose(x, y=0, z=0):
    return {'Root': SimpleNamespace(translation=Vec([x, y, z]))}


def transform(scale=(1, 1, 1), translation=(0, 0, 0), rotate=False):
    matrix = np.eye(4); matrix[:3, :3] = np.diag(scale); matrix[:3, 3] = translation
    if rotate: matrix[:3, :3] = np.array([[0,0,1],[0,1,0],[-1,0,0]]) @ matrix[:3, :3]
    return Matrix(matrix)


class WorldRootMotionTests(unittest.TestCase):
    def report(self, poses, worlds, factor=1, system='NONE'):
        rig = SimpleNamespace(data=SimpleNamespace(bones=[SimpleNamespace(name='Root', parent=None)]))
        return rig_module.root_motion_report(rig, SimpleNamespace(name='Move'), list(range(len(poses))),
                                             poses, worlds, system, factor)

    def test_legacy_local_and_scaled_world(self):
        result = self.report([pose(0), pose(2)], [transform((.01,.01,.01))]*2)
        self.assertEqual(result['root_bones'][0]['displacement'], 2)
        self.assertEqual(result['coordinate_space'], 'armature')
        self.assertAlmostEqual(result['world_space']['root_bones'][0]['displacement_m'], .02)

    def test_rotated_nonuniform_scene_scale_and_object_motion(self):
        result = self.report([pose(0),pose(2)], [transform((2,1,1),rotate=True),
            transform((2,1,1),translation=(1,0,0),rotate=True)], factor=.5, system='METRIC')
        world = result['world_space']; entry=world['root_bones'][0]
        self.assertEqual(world['meters_per_scene_unit'], .5)
        self.assertAlmostEqual(entry['horizontal_m'], .5)
        self.assertAlmostEqual(entry['vertical_m'], 2)
        self.assertAlmostEqual(entry['displacement_m'], math.sqrt(4.25))

    def test_stationary_bone_tracks_per_frame_object_motion(self):
        result=self.report([pose(0)]*3,[transform(),transform(translation=(3,0,0)),transform()])
        self.assertEqual(result['max_travel'],0)
        self.assertEqual(result['world_space']['max_travel_m'],3)
        self.assertEqual(result['world_space']['loop_distance_m'],0)

    def test_multiple_roots_and_frame_sampling(self):
        rig = SimpleNamespace(data=SimpleNamespace(bones=[SimpleNamespace(name='Root', parent=None),
                                                          SimpleNamespace(name='Other', parent=None)]))
        poses = [dict(pose(0), Other=SimpleNamespace(translation=Vec([0,0,0]))),
                 dict(pose(1), Other=SimpleNamespace(translation=Vec([0,2,0])))]
        result = rig_module.root_motion_report(rig, SimpleNamespace(name='Move'), [1,2], poses,
                                                [transform(),transform()], 'NONE', 1)
        self.assertEqual(len(result['world_space']['root_bones']), 2)
        self.assertEqual(result['world_space']['max_travel_m'], 2)

    def test_sampling_pairs_pose_with_same_frame_world(self):
        state = {'frame': 0}
        class Scene:
            def frame_set(self, frame): state['frame'] = frame
        class Current:
            @property
            def matrix(self): return SimpleNamespace(copy=lambda: state['frame'])
        class Evaluated:
            @property
            def matrix_world(self): return SimpleNamespace(copy=lambda: state['frame'] * 10)
        rig = SimpleNamespace(data=SimpleNamespace(bones=[SimpleNamespace(name='Root')]),
                              pose=SimpleNamespace(bones={'Root': Current()}),
                              evaluated_get=lambda depsgraph: Evaluated())
        bpy = SimpleNamespace(context=SimpleNamespace(scene=Scene(),
            view_layer=SimpleNamespace(update=lambda: None), evaluated_depsgraph_get=lambda: None))
        with patch.object(rig_module, 'bpy', bpy):
            poses, worlds = rig_module.pose_matrices(rig, [1, 2, 3])
        self.assertEqual([value['Root'] for value in poses], [1, 2, 3])
        self.assertEqual(worlds, [10, 20, 30])

    def test_invalid_scale_and_nonfinite_world_rejected(self):
        for factor in (None, 0, -1, float('nan'), float('inf')):
            with self.subTest(factor=factor), self.assertRaises(ValueError):
                self.report([pose(0),pose(1)],[transform()]*2,factor=factor)
        with self.assertRaises(ValueError):
            self.report([pose(0),pose(1)],[transform(),transform(translation=(float('nan'),0,0))])
