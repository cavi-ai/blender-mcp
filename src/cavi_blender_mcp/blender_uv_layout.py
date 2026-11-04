"""Read source UV loops without evaluating or changing Blender geometry."""
import bpy

from .uv_layout import MAX_TRIANGLES, analyze


def inspect(params, find_object):
    names = params['names']
    if (not isinstance(names, list) or not 1 <= len(names) <= 32
            or any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names)):
        raise ValueError('Inspect 1..32 unique mesh names')
    requested = params.get('uv_layer')
    if requested is not None and (not isinstance(requested, str) or not 1 <= len(requested) <= 63):
        raise ValueError('UV layer name must contain 1..63 characters')
    material = params.get('material')
    if material is not None and (not isinstance(material, str) or not 1 <= len(material) <= 63):
        raise ValueError('Material must be an exact 1..63 character name')
    triangles, vertices, objects = [], [], []
    vertex_offset = 0
    for name in names:
        value = find_object(name)
        if value.type != 'MESH' or value.mode != 'OBJECT':
            raise ValueError('Inspect mesh objects in Object Mode')
        mesh = value.data
        if len(mesh.loops) > MAX_TRIANGLES * 3 or len(mesh.vertices) + vertex_offset > 200000:
            raise ValueError('Source exceeds the 60000-loop or 200000-vertex budget')
        layer = mesh.uv_layers.get(requested) if requested else (
            mesh.uv_layers[0] if mesh.uv_layers else None)
        if layer is None:
            raise ValueError(f'{name}: requested UV layer is missing')
        mesh.calc_loop_triangles()
        slots, selected = {}, []
        for triangle in mesh.loop_triangles:
            index = triangle.material_index
            bound = value.material_slots[index].material if index < len(value.material_slots) else None
            name_at_slot = bound.name if bound else None
            slots.setdefault(index, {'slot': index, 'material': name_at_slot, 'triangles': 0})['triangles'] += 1
            if material is None or name_at_slot == material:
                selected.append(triangle)
        count = len(selected)
        if not mesh.loop_triangles or len(triangles) + count > MAX_TRIANGLES:
            raise ValueError(f'Inspect 1..{MAX_TRIANGLES} triangles total')
        first = len(triangles)
        for triangle in selected:
            triangles.append([tuple(layer.data[loop].uv) for loop in triangle.loops])
            vertices.append([vertex + vertex_offset for vertex in triangle.vertices])
        vertex_offset += len(mesh.vertices)
        objects.append({'name': name, 'mesh': mesh.name, 'uv_layer': layer.name,
                        'uv_layer_index': list(mesh.uv_layers).index(layer),
                        'first_triangle': first, 'triangles': count,
                        'source_triangles': len(mesh.loop_triangles),
                        'material_slots': list(slots.values()),
                        'unevaluated_modifiers': [m.type for m in value.modifiers]})
    if not triangles:
        raise ValueError('No source triangles use the requested material')
    result = analyze(triangles, vertices, params['texture_resolution'], params['padding_pixels'],
                     params.get('comparison_budget', 100000))
    return {**result, 'scope': 'source_uv_one_texture_set', 'material': material, 'objects': objects,
            'file': bpy.data.filepath, 'dirty': bpy.data.is_dirty,
            'not_checked': ['evaluated or exported UVs', 'material UV transforms',
                            'bake projection and cage', 'dilation and mip filtering']}
