"""Scalar modifier controls and conservative topology bounds."""
import math

from .native_controls import controls as native_controls


def controls(values,schema):
    """Validate the complete map against inspected native property metadata."""
    return native_controls(values,schema,subject='modifier',parameter='modifier_settings')


# Kinds whose amount drives one control and whose evaluation never adds faces.
AMOUNTS={
    'WELD':('merge_threshold',lambda a:0<a<=1),
    'DISPLACE':('strength',lambda a:a!=0 and abs(a)<=100),
    'SHRINKWRAP':('offset',lambda a:abs(a)<=100),
    'WEIGHTED_NORMAL':('weight',lambda a:a==int(a) and 1<=a<=100),
    'DATA_TRANSFER':('mix_factor',lambda a:0<a<=1)}


def update(kind,settings,amount):
    if type(amount) not in (float,int) or not math.isfinite(amount):
        raise ValueError('Modifier amount must be finite')
    if kind in AMOUNTS and AMOUNTS[kind][1](amount):
        return {AMOUNTS[kind][0]:int(amount) if kind=='WEIGHTED_NORMAL' else amount}
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
        elif kind not in ('ARMATURE','DECIMATE',*AMOUNTS):
            raise ValueError('Cannot bound this modifier stack; use a bounded working mesh')
        if triangles>500000:
            raise ValueError('Modifier stack exceeds the conservative 500000-triangle budget')
    return triangles
