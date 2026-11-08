"""Validate scalar RNA controls without coercion, clamping or partial application."""
import math
import struct


def equivalent(left,right):
    """Compare native float storage without merging distinct integer controls."""
    if isinstance(left,dict) and isinstance(right,dict):
        return left.keys()==right.keys() and all(equivalent(left[k],right[k]) for k in left)
    if isinstance(left,list) and isinstance(right,list):
        return len(left)==len(right) and all(equivalent(a,b) for a,b in zip(left,right,strict=True))
    if type(left) in (int,float) and type(right) in (int,float):
        if type(left) is int and type(right) is int:return left==right
        return struct.pack('=f',left)==struct.pack('=f',right)
    return type(left) is type(right) and left==right


def controls(values,schema,*,subject,parameter):
    if not isinstance(values,dict) or not values:
        raise ValueError(parameter+' requires a nonempty property map')
    result={}
    for key,value in values.items():
        spec=schema.get(key)
        if spec is None or spec['readonly']:
            raise ValueError(f'Unknown or read-only {subject} control: {key}')
        kind=spec['type']
        if kind=='BOOLEAN':valid=type(value) is bool
        elif kind=='ENUM':valid=type(value) is str and value in spec['items']
        elif kind=='STRING':
            valid=type(value) is str and '\0' not in value and (
                not spec.get('max_length') or len(value.encode('utf-8'))<=spec['max_length'])
        elif kind in ('INT','FLOAT'):
            valid=type(value) is int if kind=='INT' else type(value) in (int,float)
            try:valid=valid and math.isfinite(value) and spec['min']<=value<=spec['max']
            except OverflowError:valid=False
        else:valid=False
        if not valid:raise ValueError(f'Invalid native type or range for {subject} control: {key}')
        result[key]=float(value) if kind=='FLOAT' else value
    return result
