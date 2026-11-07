"""Scalar modifier controls and conservative topology bounds."""
import math


def controls(values,schema):
    """Validate the complete map against inspected native property metadata."""
    if not isinstance(values,dict) or not values:
        raise ValueError('modifier_settings requires a nonempty property map')
    result={}
    for key,value in values.items():
        spec=schema.get(key)
        if spec is None or spec['readonly']:
            raise ValueError(f'Unknown or read-only modifier control: {key}')
        kind=spec['type']
        if kind=='BOOLEAN':valid=type(value) is bool
        elif kind=='ENUM':valid=type(value) is str and value in spec['items']
        elif kind in ('INT','FLOAT'):
            valid=type(value) is int if kind=='INT' else type(value) in (int,float)
            try:valid=valid and math.isfinite(value) and spec['min']<=value<=spec['max']
            except OverflowError:valid=False
        else:valid=False
        if not valid:raise ValueError(f'Invalid native type or range for modifier control: {key}')
        result[key]=float(value) if kind=='FLOAT' else value
    return result


def update(kind,settings,amount):
    if type(amount) not in (float,int) or not math.isfinite(amount):
        raise ValueError('Modifier amount must be finite')
    if kind=='BEVEL' and settings.get('offset_type')!='PERCENT' and 0<amount<=100:
        return {'width':amount}
    if kind=='DECIMATE' and settings.get('decimate_type')=='COLLAPSE' and 0<amount<=1:
        return {'ratio':amount}
    if kind=='SUBSURF' and amount in (1,2,3):
        return {'levels':int(amount),'render_levels':int(amount)}
    if kind=='REMESH' and settings.get('mode')=='VOXEL' and .005<=amount<=1:
        return {'voxel_size':amount}
    raise ValueError('Unsupported modifier mode or amount; inspect its native settings')


def stack_bound(face_sizes,stack):
    """Bound both evaluation modes without evaluating an enlarged candidate stack."""
    triangles=sum(max(0,n-2) for n in face_sizes)
    for row in stack:
        kind=row['type']
        if kind=='BEVEL':
            segments=row['segments']
            # Three corners per source triangle bound edge/vertex incidences.
            # A second triangle per resulting face covers bevel strips and caps.
            triangles*=2*(1+3*segments+3*segments*segments)
        elif kind=='SUBSURF':
            levels=max(row['levels'],row['render_levels'])
            if levels>0:triangles*=6*4**(levels-1)
        elif kind not in ('ARMATURE','DECIMATE'):
            raise ValueError('Cannot bound this modifier stack; use a bounded working mesh')
        if triangles>500000:
            raise ValueError('Modifier stack exceeds the conservative 500000-triangle budget')
    return triangles
