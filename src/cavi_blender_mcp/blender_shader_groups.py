"""Native shader definition allocation, typed interfaces and inspection."""
import bpy

from .blender_node_inputs import encode
from .blender_shader_group_specs import blueprint
from .blender_shader_inputs import decode
from .native_controls import controls, equivalent


def validate(value):
    spec=blueprint(value)
    if bpy.data.node_groups.get(spec['name']) is not None:raise ValueError('New shader-group name already exists')
    for row in spec['interface']:
        cls=getattr(bpy.types,row['socket_type'],None)
        if not isinstance(cls,type) or not issubclass(cls,bpy.types.NodeSocket):
            raise TypeError('Socket type is not registered: '+row['socket_type'])
    return spec


def interface_report(tree):
    rows=[]
    for socket in tree.interface.items_tree:
        if socket.item_type!='SOCKET':continue
        row={key:getattr(socket,key) for key in ('name','identifier','in_out','socket_type','description')}
        for key in ('default_value','min_value','max_value'):
            if hasattr(socket,key):row[key]=encode(getattr(socket,key))
        rows.append(row)
    return rows


def create(spec,owned):
    group=bpy.data.node_groups.new(spec['name'],'ShaderNodeTree');owned.append(group)
    if group.name!=spec['name']:raise RuntimeError('Native group name differs from the requested declaration')
    group.use_fake_user=True
    for row in spec['interface']:
        socket=group.interface.new_socket(name=row['name'],in_out=row['in_out'],
            socket_type=row['socket_type'],description=row.get('description',''))
        if (socket.name!=row['name'] or socket.in_out!=row['in_out'] or socket.socket_type!=row['socket_type']):
            raise RuntimeError('Native interface differs from the requested declaration')
        for key in ('min_value','max_value'):
            if key not in row:continue
            prop=socket.bl_rna.properties.get(key)
            if prop is None or prop.type not in {'INT','FLOAT'}:raise ValueError('Socket has no native '+key)
            schema={key:{'type':prop.type,'readonly':prop.is_readonly or socket.is_property_readonly(key),
                         'min':prop.hard_min,'max':prop.hard_max}}
            value=controls({key:row[key]},schema,subject='group interface',parameter='node_tree.interface')[key]
            setattr(socket,key,value)
            if not equivalent(getattr(socket,key),value):raise RuntimeError('Native interface range differs from the request')
        if 'default_value' in row:
            value=decode(socket,row['default_value']);socket.default_value=value
            if not equivalent(encode(socket.default_value),value):
                raise RuntimeError('Native interface default differs from the request')
    return group
