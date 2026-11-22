"""Native face-bounded seam, shape-key and rollback checks."""
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_vertices

mesh = bpy.data.meshes.new('BoundedGrid')
mesh.from_pydata([(x, y, 0) for y in range(3) for x in range(3)], [],
                 [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6), (4, 5, 8, 7)])
obj = bpy.data.objects.new('BoundedGrid', mesh)
bpy.context.scene.collection.objects.link(obj)
obj.shape_key_add(name='Basis')
key = obj.shape_key_add(name='Expression')
key.data[4].co.z = .25
params = {'name': obj.name, 'vertex_indices': [4], 'face_indices': [0, 1, 2, 3],
          'offset': [0, 0, .2], 'amount': 2.,
          'expected_mesh_sha256': blender_vertices.mesh_digest(mesh)}
def state():
    return [[tuple(v.co) for v in layer] for layer in
            (mesh.vertices, *(block.data for block in mesh.shape_keys.key_blocks))]
before = state()
report = blender_vertices.move(params)['vertex_edit']
after = state()
assert report['vertex_indices'] == [4] and report['falloff']['pinned_boundary_vertices'] == 8
assert all(before[layer][i] == after[layer][i] for layer in range(3) for i in range(9) if i != 4)
assert abs((after[2][4][2] - after[1][4][2]) - .25) < 1e-6
for invalid in ({'vertex_indices': [0]}, {'expected_mesh_sha256': '0'*64}, {'amount': None}):
    try:
        blender_vertices.move({**params, **invalid})
    except ValueError:
        assert state() == after
    else:
        raise AssertionError('Invalid bounded edit accepted')
original_digest = blender_vertices.mesh_digest
count = 0
def failing_digest(value):
    global count
    count += 1
    if count == 2:
        raise RuntimeError('receipt failure')
    return original_digest(value)
params['expected_mesh_sha256'] = original_digest(mesh)
blender_vertices.mesh_digest = failing_digest
try:
    try:
        blender_vertices.move(params)
    except RuntimeError:
        assert state() == after
    else:
        raise AssertionError('Receipt failure did not rollback')
finally:
    blender_vertices.mesh_digest = original_digest
print('Bounded vertex region, seam, shape keys and rollback passed')
