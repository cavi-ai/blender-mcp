"""Validate complete native ramp requests before changing collection elements."""
import math
import struct

from .native_controls import controls


def equivalent(left,right):
    """Compare exactly at the native collection's float storage precision."""
    if isinstance(left,dict) and isinstance(right,dict):
        return left.keys()==right.keys() and all(equivalent(left[k],right[k]) for k in left)
    if isinstance(left,list) and isinstance(right,list):
        return len(left)==len(right) and all(equivalent(a,b) for a,b in zip(left,right,strict=True))
    if type(left) in (int,float) and type(right) in (int,float):
        return struct.pack('=f',left)==struct.pack('=f',right)
    return left==right


def settings(values,schema):
    if not isinstance(values,dict) or not values:
        raise ValueError('set_ramp requires nonempty node_settings')
    enums={key:value for key,value in values.items() if key!='elements'}
    result=controls(enums,schema['controls'],subject='color ramp',parameter='node_settings') if enums else {}
    if 'elements' not in values:return result
    elements=values['elements']
    if not isinstance(elements,list) or not schema['min_elements']<=len(elements)<=schema['max_elements']:
        raise ValueError('Ramp element count exceeds native bounds')

    def number(value,spec):
        try:valid=type(value) in (int,float) and math.isfinite(value) and spec['min']<=value<=spec['max']
        except OverflowError:valid=False
        if not valid:raise ValueError('Ramp values require finite numbers within native bounds')
        return float(value)

    rows=[]
    for row in elements:
        if not isinstance(row,dict) or set(row)!={'position','color'}:
            raise ValueError('Each ramp element requires position and color only')
        color=row['color']
        if not isinstance(color,list) or len(color)!=4:
            raise ValueError('Ramp colors require scene-linear RGBA')
        rows.append({'position':number(row['position'],schema['position']),
                     'color':[number(v,schema['color']) for v in color]})
    result['elements']=sorted(rows,key=lambda row:row['position'])
    return result
