"""Optional neural-runtime geometry checks, without loading model weights."""

import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp.neural_worker import clean_mesh

sphere = trimesh.creation.icosphere(subdivisions=2)
sphere.visual.vertex_colors = np.tile([180, 80, 30, 255], (len(sphere.vertices), 1))
noise = trimesh.Trimesh(vertices=[[10, 0, 0], [11, 0, 0], [10, 1, 0]], faces=[[0, 1, 2]])
result = clean_mesh(trimesh.util.concatenate([sphere, noise]))
assert len(result.faces) == 320
assert result.vertices.max() < 2
assert result.is_watertight
assert len(result.visual.vertex_colors) == len(result.vertices)
assert result.visual.vertex_colors[:, 0].min() == 180
print("Neural geometry checks passed")
