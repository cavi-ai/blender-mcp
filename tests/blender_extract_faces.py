"""Native face subsets retain source data and remove only failed output IDs."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cavi_blender_mcp import blender_bridge as bridge
from cavi_blender_mcp import blender_compose
from cavi_blender_mcp.blender_asset_library import ids


def attribute_values(attribute):
    key = {'FLOAT_VECTOR': 'vector', 'FLOAT2': 'vector', 'FLOAT_COLOR': 'color',
           'BYTE_COLOR': 'color'}.get(attribute.data_type, 'value')
    return [tuple(getattr(item, key)) if item.bl_rna.properties[key].is_array
            else getattr(item, key) for item in attribute.data]


def snapshot(value):
    mesh = value.data
    return {'vertices': [tuple(v.co) for v in mesh.vertices],
            'edges': [(tuple(e.vertices), e.use_seam, e.use_edge_sharp) for e in mesh.edges],
            'faces': [(tuple(p.vertices), p.material_index, p.use_smooth) for p in mesh.polygons],
            'attributes': {a.name: (a.domain, a.data_type, attribute_values(a))
                           for a in mesh.attributes},
            'properties': dict(mesh.items()),
            'slots': [(s.link, s.material) for s in value.material_slots],
            'uv_active': mesh.uv_layers.active_index,
            'uv_render': [u.active_render for u in mesh.uv_layers],
            'world': [list(row) for row in value.matrix_world], 'parent': value.parent}


with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    mesh = bpy.data.meshes.new('Surface')
    mesh.from_pydata([(0, 0, 0), (1, 0, 0), (2, 0, 0), (0, 1, 0), (1, 1, 0),
                      (2, 1, 0), (0, 2, 0), (1, 2, 0), (9, 9, 9)], [],
                     [(0, 1, 4, 3), (1, 2, 5, 4), (3, 4, 7, 6)])
    value = bpy.data.objects.new('Surface', mesh)
    bpy.context.scene.collection.objects.link(value)
    holder = bpy.data.objects.new('Assembly', None)
    bpy.context.scene.collection.objects.link(holder)
    holder.location = (2, -1, .5)
    value.parent = holder
    value.location, value.rotation_euler, value.scale = (.2, .3, .4), (.1, .2, .3), (-1, 2, .5)
    for name in ('Base', 'Trim'):
        mesh.materials.append(bpy.data.materials.new(name))
    value.material_slots[1].link = 'OBJECT'
    value.material_slots[1].material = bpy.data.materials.new('Override')
    for face in mesh.polygons:
        face.material_index, face.use_smooth = int(face.index != 0), bool(face.index)
    for index, edge in enumerate(mesh.edges):
        edge.use_seam, edge.use_edge_sharp = bool(index % 2), bool(index % 3)
    for index, name in enumerate(('UVMap', 'Paint')):
        layer = mesh.uv_layers.new(name=name)
        for loop in mesh.loops:
            layer.data[loop.index].uv = (index + .03 * loop.index, .2 + .01 * loop.index)
    mesh.uv_layers.active_index = 1
    mesh.uv_layers[0].active_render = True
    mesh['authoring_label'] = 'surface source'
    specifications = [('point_weight', 'FLOAT', 'POINT'), ('edge_code', 'INT', 'EDGE'),
                      ('face_flag', 'BOOLEAN', 'FACE'), ('corner_vector', 'FLOAT_VECTOR', 'CORNER'),
                      ('corner_color', 'FLOAT_COLOR', 'CORNER')]
    for name, kind, domain in specifications:
        attribute = mesh.attributes.new(name, kind, domain)
        for index, item in enumerate(attribute.data):
            if kind == 'FLOAT_VECTOR':
                item.vector = (index, index + 1, index + 2)
            elif kind == 'FLOAT_COLOR':
                item.color = (.01 * index, .02 * index, .03 * index, 1)
            else:
                item.value = bool(index) if kind == 'BOOLEAN' else index
    mesh.normals_split_custom_set([(0.1, 0.2, 1)] * len(mesh.loops))
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = value
    value.select_set(True)
    before, original_mesh = snapshot(value), value.data
    context = (set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    state = bridge.dispatch('session_control', {'action': 'inspect'})
    lease = bridge.dispatch('session_control', {'action': 'claim', 'owner': 'face-extraction',
        'expected_project': state['project_id']})['lease_id']

    def extract(**extra):
        return bridge.dispatch('owned_edit', {'operation': 'extract_faces', 'params': {
            'name': value.name, 'new_name': 'Patch', 'face_indices': [2, 0],
            'lease_id': lease, **extra}})

    def refused(**extra):
        before_ids, before_case = ids(), snapshot(value)
        try:
            extract(**extra)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid extraction was accepted')
        assert ids() == before_ids and snapshot(value) == before_case

    for selection in ([], [0, 0], [0, 99], [-1], [True], [1.5], [0] * 20001):
        refused(face_indices=selection)
    refused(new_name=value.name)
    group = value.vertex_groups.new(name='Head')
    refused()
    value.vertex_groups.remove(group)
    modifier = value.modifiers.new('Subdivision', 'SUBSURF')
    refused()
    value.modifiers.remove(modifier)
    value.shape_key_add(name='Basis')
    refused()
    value.shape_key_clear()
    holder.scale = (2, 1, .5)
    bpy.context.view_layer.update()
    refused()
    holder.scale, value.scale = (1, 1, 1), (0, 2, .5)
    bpy.context.view_layer.update()
    refused()
    value.scale = (-1, 2, .5)
    bpy.context.view_layer.update()
    before_ids = ids()
    with patch.object(blender_compose, 'info', side_effect=RuntimeError('receipt failure')):
        try:
            extract()
        except RuntimeError as exc:
            assert str(exc) == 'receipt failure'
        else:
            raise AssertionError('Expected receipt failure')
    assert ids() == before_ids and snapshot(value) == before
    result = extract()
    bpy.context.view_layer.update()
    output = bpy.data.objects[result['name']]
    assert output.data != original_mesh and output.parent is None and not output.vertex_groups
    assert not output.modifiers and output.data.shape_keys is None
    assert [list(row) for row in output.matrix_world] == before['world']
    assert snapshot(value) == before and value.data == original_mesh
    assert context == (set(bpy.context.selected_objects), bpy.context.view_layer.objects.active)
    assert result['face_indices'] == [0, 2] and result['triangles'] == 4
    assert len(output.data.polygons) == 2 and len(output.data.vertices) == 6
    assert dict(output.data.items()) == before['properties']
    assert [(s.link, s.material) for s in output.material_slots] == before['slots']
    assert output.data.uv_layers.active_index == 1 and output.data.uv_layers[0].active_render
    points = {tuple(v.co): v.index for v in mesh.vertices}
    point_map = [points[tuple(v.co)] for v in output.data.vertices]
    edge_ids = {frozenset(e.vertices): e.index for e in mesh.edges}
    edge_map = [edge_ids[frozenset(point_map[i] for i in e.vertices)] for e in output.data.edges]
    face_map, corner_map = [], []
    for face in output.data.polygons:
        vertices = tuple(point_map[i] for i in face.vertices)
        original = next(p for p in mesh.polygons if tuple(p.vertices) == vertices)
        face_map.append(original.index)
        corner_map.extend(original.loop_indices)
        assert (face.material_index, face.use_smooth) == (original.material_index, original.use_smooth)
    maps = {'POINT': point_map, 'EDGE': edge_map, 'FACE': face_map, 'CORNER': corner_map}
    for name, _kind, domain in specifications:
        assert attribute_values(output.data.attributes[name]) == [
            attribute_values(mesh.attributes[name])[i] for i in maps[domain]], name
    for original, copied in zip(mesh.uv_layers, output.data.uv_layers, strict=True):
        assert [tuple(v.uv) for v in copied.data] == [tuple(original.data[i].uv) for i in corner_map]
    assert output.data.has_custom_normals
    assert max((output.data.corner_normals[i].vector - mesh.corner_normals[original].vector).length
               for i, original in enumerate(corner_map)) < 1e-6
    print(json.dumps({'extract_faces': 'passed', 'source_exact': True, 'triangles': 4,
        'uv_layers': 2, 'custom_attribute_domains': sorted(maps), 'receipt_rollback': True,
        'invalid_selection_modifier_shape_key_weights_refused': True,
        'sheared_and_singular_transforms_refused': True, 'custom_normals_preserved': True}))
