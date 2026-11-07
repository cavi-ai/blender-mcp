"""Validate exact shader socket bindings independently of Blender."""


def bindings(value):
    if not isinstance(value,dict) or not 1<=len(value)<=32:
        raise ValueError('Link inputs require 1 to 32 socket bindings')
    for identifier,source in value.items():
        if (not isinstance(identifier,str) or not identifier or len(identifier)>255
                or not isinstance(source,dict) or set(source)!={'node','socket'}
                or any(not isinstance(source[k],str) or not source[k] or len(source[k])>255
                       for k in ('node','socket'))):
            raise ValueError('Link bindings require input ID: {node: exact name, socket: output ID}')
    return value


def compatible(source,target):
    # ShaderNodeTree conversions: numeric/color may feed emission; shaders cannot feed data.
    if source=='SHADER':
        return target=='SHADER'
    if {source,target}&{'BUNDLE','CLOSURE','MENU'}:
        return source==target
    return True
