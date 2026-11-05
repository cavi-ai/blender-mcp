"""Transform explicit source-face UV loops without rebuilding mesh data."""
import math

import bpy

from .blender_errors import preflight


def pair(value, label):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in value)):
        raise ValueError(f'{label} requires two finite numbers within +/-1000000')
    return value


def bounds(rows):
    return [[min(uv[i] for _, uv in rows) for i in range(2)],
            [max(uv[i] for _, uv in rows) for i in range(2)]]


def write(layer, rows):
    for index, uv in rows:
        layer.data[index].uv = uv


def transform(params, editable_mesh, info):
    with preflight():
        value = editable_mesh(params['name'])
        mesh = value.data
        if bpy.context.mode != 'OBJECT' or value.mode != 'OBJECT':
            raise ValueError('UV editing requires Object Mode')
        if not mesh.is_editable:
            raise ValueError('UV editing requires editable local mesh data')
        name = params.get('uv_layer')
        if name is not None and (not isinstance(name, str) or not 1 <= len(name.encode()) <= 63):
            raise ValueError('UV layer name must contain 1..63 UTF-8 bytes')
        layer = mesh.uv_layers.get(name) if name is not None else (
            mesh.uv_layers[0] if mesh.uv_layers else None)
        if layer is None:
            raise ValueError('Requested UV layer is missing')
        spec = params.get('transform')
        if not isinstance(spec, dict) or set(spec) - {'faces','offset','scale','rotation_degrees','pivot'}:
            raise ValueError('Expected a UV transform with explicit faces')
        faces = spec.get('faces')
        if (not isinstance(faces, list) or not 1 <= len(faces) <= 20000
                or any(type(f) is not int or not 0 <= f < len(mesh.polygons) for f in faces)
                or len(set(faces)) != len(faces)):
            raise ValueError('Select 1..20000 unique existing source face indices')
        offset = pair(spec.get('offset', (0,0)), 'offset')
        scale = pair(spec.get('scale', (1,1)), 'scale')
        pivot = pair(spec.get('pivot', (0,0)), 'pivot')
        angle = spec.get('rotation_degrees', 0)
        if type(angle) not in (int,float) or not math.isfinite(angle) or abs(angle) > 360000:
            raise ValueError('rotation_degrees must be finite within +/-360000')
        polygons = [mesh.polygons[index] for index in faces]
        if sum(p.loop_total for p in polygons) > 60000:
            raise ValueError('Selected faces exceed 60000 UV loops')
        before = [(i, tuple(layer.data[i].uv)) for p in polygons for i in p.loop_indices]
        cosine, sine = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        after = []
        for index, uv in before:
            x, y = (uv[i]-pivot[i] for i in range(2))
            x, y = x*scale[0], y*scale[1]
            target = (pivot[0]+cosine*x-sine*y+offset[0],
                      pivot[1]+sine*x+cosine*y+offset[1])
            after.append((index, tuple(pair(target, 'transformed UV'))))
        materials = list(dict.fromkeys(
            value.material_slots[p.material_index].material.name
            if p.material_index < len(value.material_slots) and value.material_slots[p.material_index].material
            else None for p in polygons))
    try:
        write(layer, after)
        mesh.update()
        actual = [(i, tuple(layer.data[i].uv)) for i, _ in after]
        if any(not math.isclose(a,b,rel_tol=1e-6,abs_tol=1e-6)
               for (_,uv),(_,target) in zip(actual,after,strict=True)
               for a,b in zip(uv,target,strict=True)):
            raise RuntimeError('Native UV readback differs from the requested transform')
        return {**info(value), 'uv_layer':layer.name, 'uv_transform':{
            'faces':faces, 'loops':len(after), 'materials':materials,
            'bounds_before':bounds(before), 'bounds_after':bounds(actual),
            'offset':list(offset), 'scale':list(scale), 'rotation_degrees':angle, 'pivot':list(pivot)}}
    except Exception:
        # Restore independently of the write helper, including a partial write failure.
        for index, uv in before:
            layer.data[index].uv = uv
        mesh.update()
        raise
