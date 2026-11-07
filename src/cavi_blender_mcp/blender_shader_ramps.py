"""Atomic native ColorRamp authoring, including shared and animated graph guards."""
import re

import bpy

from .blender_animation_refs import bound_curves
from .blender_errors import preflight
from .blender_ramp_settings import equivalent, settings
from .blender_shader_inputs import editable_node, finish_edit, update

FIELDS=('interpolation','color_mode','hue_interpolation')


def read(ramp):
    return {**{key:getattr(ramp,key) for key in FIELDS},
        'elements':[{'position':e.position,'color':list(e.color)} for e in ramp.elements]}


def control_schema(ramp):
    enums={}
    for key in FIELDS:
        prop=ramp.bl_rna.properties[key]
        enums[key]={'type':'ENUM','readonly':prop.is_readonly or ramp.is_property_readonly(key),
                    'items':[item.identifier for item in prop.enum_items if item.identifier]}
    element=ramp.elements[0]
    return {'controls':enums,'min_elements':1,'max_elements':32,
        **{key:{'min':element.bl_rna.properties[key].hard_min,'max':element.bl_rna.properties[key].hard_max}
           for key in ('position','color')}}


def references(owner,path,ramp):
    if owner is None:return False
    for match in re.finditer(r'(?:^|\.)color_ramp(?=\.|\[|$)',path):
        try:
            if owner.path_resolve(path[:match.end()],False)==ramp:return True
        except (ValueError,KeyError,TypeError):
            continue
    return False


def require_static(ramp):
    mapping=bpy.data.user_map()
    owners=set(mapping)
    for users in mapping.values():owners.update(users)
    owners.add(ramp.id_data)
    owners.update(tree for owner in tuple(owners) if (tree:=getattr(owner,'node_tree',None)) is not None)
    for owner in owners:
        if any(references(owner,curve.data_path,ramp) for curve in bound_curves(owner)):
            raise ValueError('Ramp is animated or driven; edit its animation before changing static ramp data')
        animation=getattr(owner,'animation_data',None)
        for curve in animation.drivers if animation else ():
            for variable in curve.driver.variables:
                if any(references(t.id,t.data_path,ramp) for t in variable.targets):
                    raise ValueError('A driver references this ramp; detach that reference before editing')


def apply(ramp,values):
    for key in FIELDS:
        if key in values:setattr(ramp,key,values[key])
    if 'elements' not in values:return
    elements=values['elements']
    while len(ramp.elements)>1:ramp.elements.remove(ramp.elements[-1])
    ramp.elements[0].position=0
    while len(ramp.elements)<len(elements):ramp.elements.new(0)
    for index in reversed(range(len(elements))):ramp.elements[index].position=elements[index]['position']
    for index,row in enumerate(elements):ramp.elements[index].color=row['color']


def set_ramp(params):
    with preflight():
        tree,node=editable_node(params)
        ramp=getattr(node,'color_ramp',None)
        if getattr(getattr(ramp,'bl_rna',None),'identifier',None)!='ColorRamp':
            raise ValueError('Node has no native ColorRamp')
        values=settings(params.get('node_settings'),control_schema(ramp))
        before=read(ramp)
        expected={**before,**values}
        changed=not equivalent(before,expected)
        if changed:require_static(ramp)
    try:
        if changed:
            apply(ramp,values)
            update(tree)
            if not equivalent(read(ramp),expected):raise RuntimeError('Native ramp readback differs from the requested edit')
        return finish_edit(params,tree,changed,changed_ramp=changed)
    except Exception:
        if changed:
            apply(ramp,before)
            update(tree)
        raise
