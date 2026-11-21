"""Scene inspection mode checks shared by the contract and native handlers."""


def require_scene_mode(value):
    if isinstance(value,dict):
        vertices = value.get('vertices')
        if value.get('scope') == 'source_mesh_vertices':
            if not isinstance(vertices,list):
                raise ValueError('Source vertex pages require a vertex list')
        elif vertices is not None and (type(vertices) is not int or vertices < 0):
            raise ValueError('Named-object vertices require a nonnegative integer count')
        if value.get('scope') in {'mesh_surface_pick','scene_surface_pick'}:
            pick = value.get('surface_pick')
            if not isinstance(pick,dict) or type(pick.get('hit')) is not bool:
                raise ValueError('Surface picks require an explicit hit or miss')
            if value['scope']=='scene_surface_pick' and pick['hit']:
                mapping=pick.get('source_mapping')
                if not isinstance(mapping,dict) or type(mapping.get('available')) is not bool:
                    raise ValueError('Scene hits require explicit source mapping availability')
                if not mapping['available'] and any(k in pick for k in ('face_index','triangle_vertices','triangle_loops','uv')):
                    raise ValueError('Unmapped scene geometry cannot report editable source faces or UVs')
    return value
