"""Declarative shader-group interfaces without numeric coercion."""
import math


def text(value,*,empty=False):
    if not isinstance(value,str) or (not empty and not value) or '\0' in value:
        raise ValueError('Group and socket labels require native strings without NUL')
    return value


def blueprint(value):
    if not isinstance(value,dict) or 'name' not in value or set(value)-{'name','interface'}:
        raise ValueError('New node_tree requires name and optional interface')
    name=text(value['name']);rows=value.get('interface',[])
    if not isinstance(rows,list):raise TypeError('Group interface must be a socket list')
    result=[]
    for row in rows:
        required={'name','in_out','socket_type'}
        if (not isinstance(row,dict) or not required<=set(row)
                or set(row)-required-{'description','default_value','min_value','max_value'}):
            raise ValueError('Socket requires name, in_out, socket_type and supported initial values')
        text(row['name'],empty=True);text(row['socket_type'])
        if row['in_out'] not in ('INPUT','OUTPUT'):raise ValueError('Socket in_out must be INPUT or OUTPUT')
        if 'description' in row:text(row['description'],empty=True)
        for key in ('min_value','max_value'):
            if key in row:
                try:valid=type(row[key]) in (int,float) and math.isfinite(row[key])
                except OverflowError:valid=False
                if not valid:raise ValueError('Interface ranges require finite native numbers')
        if 'min_value' in row and 'max_value' in row and row['min_value']>row['max_value']:
            raise ValueError('Interface minimum exceeds maximum')
        result.append(dict(row))
    return {'name':name,'interface':result}


def declaration_schema():
    return {'type':['string','object'],'required':['name'],'additionalProperties':False,
        'properties':{'name':{'type':'string','minLength':1},'interface':{'type':'array','items':{
            'type':'object','required':['name','in_out','socket_type'],'additionalProperties':False,
            'properties':{'name':{'type':'string'},'in_out':{'enum':['INPUT','OUTPUT']},
                'socket_type':{'type':'string','examples':['NodeSocketFloat','NodeSocketColor','NodeSocketVector','NodeSocketShader']},
                'description':{'type':'string'},'default_value':{},'min_value':{'type':'number'},'max_value':{'type':'number'}}}}}}
