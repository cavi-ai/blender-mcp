"""Discover and create configured native shader nodes without rebuilding graphs."""
import bpy

from .blender_errors import preflight
from .blender_node_inputs import matches
from .blender_shader_group_specs import declaration_schema
from .blender_shader_inputs import finish_edit, target, update
from .native_controls import controls


def available(cls,tree):
    if (not isinstance(cls,type) or not issubclass(cls,bpy.types.Node)
            or not cls.is_registered_node_type()):return False
    # Generic group I/O uses the definition context rather than its RNA poll callback.
    if cls.bl_rna.identifier in {'NodeGroupInput','NodeGroupOutput'}:
        return not tree.is_embedded_data
    return cls.poll(tree)


def node_class(kind,tree):
    cls=getattr(bpy.types,kind,None) if isinstance(kind,str) else None
    if not available(cls,tree):
        raise ValueError('Node type is not available in this shader tree: '+str(kind))
    return cls


def control_schema(cls,node=None):
    inherited=set(bpy.types.Node.bl_rna.properties.keys())
    result={}
    for prop in cls.bl_rna.properties:
        if (prop.identifier in inherited or prop.type not in {'BOOLEAN','INT','FLOAT','ENUM','STRING'}
                or getattr(prop,'is_array',False) or getattr(prop,'subtype','') in {'FILE_PATH','DIR_PATH'}):
            continue
        spec={'type':prop.type,'readonly':prop.is_readonly or bool(node and node.is_property_readonly(prop.identifier))}
        if prop.type in {'INT','FLOAT'}:
            spec.update(min=prop.hard_min,max=prop.hard_max)
        elif prop.type=='ENUM':
            spec['items']=[item.identifier for item in prop.enum_items if item.identifier]
        elif prop.type=='STRING':
            spec['max_length']=getattr(prop,'length_max',0)
        result[prop.identifier]=spec
    return result


def resource_schema(cls):
    return {'node_tree':{**declaration_schema(),'parameter':'node_settings.node_tree',
        'id_type':'NODETREE','tree_type':'ShaderNodeTree'}} if cls.bl_rna.identifier=='ShaderNodeGroup' else {}


def resources(settings,cls,tree):
    if 'node_tree' not in settings or 'node_tree' not in resource_schema(cls):return {},settings
    name=settings['node_tree']
    if isinstance(name,dict):
        from .blender_shader_groups import validate

        return {'node_tree':validate(name)},{key:value for key,value in settings.items() if key!='node_tree'}
    if not isinstance(name,str) or not name:raise ValueError('node_tree requires an exact native shader-group name')
    group=bpy.data.node_groups.get(name)
    if group is None or group.bl_idname!='ShaderNodeTree':
        raise ValueError('node_tree must name an existing ShaderNodeTree')
    pending,seen=[group],set()
    while pending:
        current=pending.pop()
        if current==tree:raise ValueError('Shader group binding would create recursion')
        if current in seen:continue
        seen.add(current)
        pending.extend(child for node in current.nodes if (child:=getattr(node,'node_tree',None)) is not None)
    return {'node_tree':group},{key:value for key,value in settings.items() if key!='node_tree'}


def inspect_types(params):
    material,tree=target(params)
    if tree is None:
        raise ValueError('Material has no shader node tree')
    kind=params.get('node_type')
    if kind is not None:
        classes=[node_class(kind,tree)]
    else:
        classes=[]
        for name in dir(bpy.types):
            cls=getattr(bpy.types,name)
            if available(cls,tree):
                classes.append(cls)
    offset,limit=params.get('offset',0),params.get('limit',100)
    if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=1000:
        raise ValueError('Use nonnegative offset and limit from 1 to 1000')
    rows=[]
    for cls in sorted(classes,key=lambda c:c.bl_rna.identifier)[offset:offset+limit]:
        row={'type':cls.bl_rna.identifier,'label':cls.bl_rna.name}
        if kind is not None:
            row['control_schema']=control_schema(cls)
            if bindings:=resource_schema(cls):row['resource_schema']=bindings
        rows.append(row)
    return {'material':material.name,'node_tree':tree.name,'group_path':params.get('group_path',[]),
            'node_types':rows,'total':len(classes),'offset':offset,'limit':limit}


def active_outputs(tree):
    return [(node,node.is_active_output) for node in tree.nodes if hasattr(node,'is_active_output')]


def restore_outputs(snapshot):
    for node,active in snapshot:
        if node.is_active_output!=active:node.is_active_output=active


def create(params):
    with preflight():
        _material,tree=target(params)
        if tree is None or not tree.is_editable:
            raise ValueError('Shader node tree needs an editable local copy or library override')
        name=params.get('node')
        if not isinstance(name,str) or not name.strip() or len(name.encode('utf-8'))>63 or name in tree.nodes:
            raise ValueError('Node name must be unique, nonempty and at most 63 UTF-8 bytes')
        cls=node_class(params.get('node_type'),tree)
        settings=params.get('node_settings',{})
        if not isinstance(settings,dict) or len(settings)>32:
            raise ValueError('node_settings must contain at most 32 native properties')
        bindings,settings=resources(settings,cls,tree)
        values=controls(settings,control_schema(cls),subject='shader node',parameter='node_settings') if settings else {}
        before=active_outputs(tree)
        prior=set(tree.nodes)
    node=None
    owned_groups=[]
    try:
        node=tree.nodes.new(cls.bl_rna.identifier)
        node.name=name
        for key,value in bindings.items():
            if isinstance(value,dict):
                from .blender_shader_groups import create as create_group

                value=create_group(value,owned_groups);bindings[key]=value
            setattr(node,key,value)
        if 'is_active_output' not in values:
            restore_outputs(before)
        for key,value in values.items():
            setattr(node,key,value)
        update(tree)
        if (node.name!=name or any(not matches(getattr(node,key),value) for key,value in values.items())
                or any(getattr(node,key)!=value for key,value in bindings.items())):
            raise RuntimeError('Native node settings differ from the requested creation')
        created={'name':node.name,'type':node.bl_idname,'settings':{key:getattr(node,key) for key in values}}
        if bindings:created['resources']={key:{'name':value.name,'id_type':value.id_type,'tree_type':value.bl_idname,
            'created':value in owned_groups}
            for key,value in bindings.items()}
        return finish_edit({**params,'node':name},tree,True,created_node=created)
    except Exception:
        for added in set(tree.nodes)-prior:tree.nodes.remove(added)
        restore_outputs(before)
        for group in reversed(owned_groups):bpy.data.node_groups.remove(group)
        update(tree)
        raise
