"""Object-owned modifier inspection and named edits; base mesh data stays intact."""
import math

import bpy

from .blender_errors import preflight
from .modifier_settings import controls, stack_bound, update

FIELDS={
    'BEVEL':('width','width_pct','segments','profile','offset_type','limit_method','angle_limit','use_clamp_overlap','harden_normals'),
    'DECIMATE':('ratio','decimate_type','iterations','angle_limit','use_collapse_triangulate'),
    'SUBSURF':('levels','render_levels','subdivision_type','show_only_control_edges','use_limit_surface'),
    'REMESH':('mode','voxel_size','octree_depth','scale','adaptivity','use_smooth_shade','use_remove_disconnected','threshold')}


def control_schema(modifier):
    result={}
    for key in (*FIELDS.get(modifier.type,()),'show_viewport','show_render'):
        prop=modifier.bl_rna.properties.get(key)
        if prop is None or getattr(prop,'is_array',False):continue
        row={'type':prop.type,'readonly':prop.is_readonly or modifier.is_property_readonly(key)}
        if prop.type in ('INT','FLOAT'):
            row.update(min=prop.hard_min,max=prop.hard_max,subtype=prop.subtype)
        elif prop.type=='ENUM':row['items']=[item.identifier for item in prop.enum_items if item.identifier]
        elif prop.type!='BOOLEAN':continue
        result[key]=row
    return result


def inspect(modifier,*,detailed=False):
    result={'name':modifier.name,'type':modifier.type,
            'show_viewport':modifier.show_viewport,'show_render':modifier.show_render,
            'settings':{key:getattr(modifier,key) for key in FIELDS.get(modifier.type,()) if hasattr(modifier,key)}}
    if detailed:result['control_schema']=control_schema(modifier)
    return result


def bound_curves(owner):
    animation=getattr(owner,'animation_data',None)
    if animation is None:return
    yield from animation.drivers
    bindings=[(animation.action,animation.action_slot)]
    pending=[strip for track in animation.nla_tracks for strip in track.strips]
    while pending:
        strip=pending.pop()
        pending.extend(getattr(strip,'strips',()))
        if strip.action is not None:bindings.append((strip.action,strip.action_slot))
    for action,slot in bindings:
        if action is None:continue
        yield from getattr(action,'fcurves',())
        for layer in action.layers:
            for strip in layer.strips:
                for bag in getattr(strip,'channelbags',()):
                    if slot is None or bag.slot_handle==slot.handle:yield from bag.fcurves


def references(owner,modifier,properties=None):
    index=list(owner.modifiers).index(modifier)
    count=len(owner.modifiers)
    prefixes=[modifier.path_from_id()]
    # Removal also shifts positive indices after the target and negative indices before it.
    positions=range(index,count) if properties is None else (index,)
    prefixes.extend(f'modifiers[{i}]' for i in positions)
    positions=range(index+1) if properties is None else (index,)
    prefixes.extend(f'modifiers[{i-count}]' for i in positions)
    paths={prefix+'.'+key for prefix in prefixes for key in properties} if properties is not None else None

    def matches(path):
        return path in paths if paths is not None else (
            any(path==prefix or path.startswith((prefix+'.',prefix+'[')) for prefix in prefixes))

    if any(matches(curve.data_path) for curve in bound_curves(owner)):
        raise ValueError('Modifier control is animated or driven; edit its animation before changing the static control')
    if properties is None:
        for user in bpy.data.user_map(subset=(owner,)).get(owner,()):
            animation=getattr(user,'animation_data',None)
            for curve in animation.drivers if animation else ():
                for variable in curve.driver.variables:
                    if any(target.id==owner and matches(target.data_path) for target in variable.targets):
                        raise ValueError('A driver references this modifier; detach that reference before removal')


def edit(params,lookup,info):
    with preflight():
        value=lookup(params['name'],mesh=True)
        if not value.is_editable or value.mode!='OBJECT' or bpy.context.mode!='OBJECT':
            raise ValueError('Modifier edits require an editable object in Object Mode')
        modifier=value.modifiers.get(params['modifier_name'])
        if modifier is None:
            raise ValueError('Named modifier does not exist; inspect the stack again')
        removing=params['action']=='remove'
        changes={}
        if not removing:
            settings=params.get('modifier_settings')
            changes=(controls(settings,control_schema(modifier)) if settings is not None
                     else update(modifier.type,inspect(modifier)['settings'],params['amount']))
            if any(modifier.is_property_readonly(key) for key in changes):
                raise ValueError('Requested modifier control is read-only')
            disabling=set(changes)<={'show_viewport','show_render'} and all(setting is False for setting in changes.values())
            if disabling:
                pass
            elif modifier.type=='REMESH':
                if len(value.modifiers)!=1 or value.data.shape_keys is not None:
                    raise ValueError('Remesh update needs a standalone modifier on a shape-key-free working mesh')
                projected={**inspect(modifier)['settings'],**changes}
                if projected['mode']=='VOXEL':
                    size=projected['voxel_size']
                    if size<=0:raise ValueError('Voxel size must be positive to bound evaluation cost')
                    bounds=[tuple(v.co) for v in value.data.vertices]
                    extents=[max((v[i] for v in bounds),default=0)-min((v[i] for v in bounds),default=0) for i in range(3)]
                    cells=math.prod(max(v,size)/size+2 for v in extents)
                else:cells=2**(3*projected['octree_depth'])
                if cells>2000000:
                    raise ValueError('Remesh update exceeds 2000000 bounding cells')
            else:
                rows=[]
                for item in value.modifiers:
                    row={'type':item.type,**inspect(item)['settings']}
                    if item==modifier:row.update(changes)
                    rows.append(row)
                stack_bound([len(f.vertices) for f in value.data.polygons],rows)
        references(value,modifier,None if removing else changes)
        previous={key:getattr(modifier,key) for key in changes}
    if removing:
        value.modifiers.remove(modifier)
        return info(value)
    try:
        for key,setting in changes.items():setattr(modifier,key,setting)
        for key,setting in changes.items():
            actual=getattr(modifier,key)
            if (isinstance(setting,float) and not math.isclose(actual,setting,rel_tol=1e-6,abs_tol=1e-7)
                    or not isinstance(setting,float) and actual!=setting):
                raise RuntimeError('Native modifier settings differ from the requested update')
        value.update_tag()
        return info(value)
    except Exception:
        for key,setting in previous.items():setattr(modifier,key,setting)
        value.update_tag()
        raise
