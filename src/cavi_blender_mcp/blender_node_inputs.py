"""Inspect procedural interfaces, edit modifier-local values and snapshot evaluated meshes."""

import math

import bpy

from .blender_bridge import info, new_name, obj
from .blender_geometry import MAX_TRIANGLES, triangle_count

REFERENCES = {'NodeSocketObject': ('objects', 'OBJECT'), 'NodeSocketCollection': ('collections', 'COLLECTION'),
              'NodeSocketMaterial': ('materials', 'MATERIAL'), 'NodeSocketImage': ('images', 'IMAGE')}
ARRAYS = {'NodeSocketVector': 3, 'NodeSocketColor': 4, 'NodeSocketRotation': 3}


class InputStore:
    """Blender 5.2 RNA inputs and earlier modifier ID properties."""

    def __init__(self, item):
        self.item = item
        self.native = getattr(getattr(item, 'properties', None), 'inputs', None)

    def property(self, key):
        field = 'value'
        for suffix, native in [('_use_attribute', 'type'), ('_attribute_name', 'attribute_name')]:
            if key.endswith(suffix):
                key, field = key[:-len(suffix)], native
                break
        return getattr(self.native, key, None), field

    def __contains__(self, key):
        if self.native is None:
            return key in self.item
        owner, field = self.property(key)
        return owner is not None and hasattr(owner, field)

    def get(self, key, default=None):
        if self.native is None:
            return self.item.get(key, default)
        owner, field = self.property(key)
        result = getattr(owner, field, default)
        return result == 'ATTRIBUTE' if field == 'type' else result

    def __setitem__(self, key, value):
        if self.native is None:
            self.item[key] = value
        else:
            owner, field = self.property(key)
            setattr(owner, field, ('ATTRIBUTE' if value else 'VALUE') if field == 'type' else value)

    def __delitem__(self, key):
        if self.native is not None:
            raise ValueError('Native input properties cannot be removed')
        del self.item[key]


def host(name):
    value = obj(name)
    if not hasattr(value, 'modifiers'):
        raise ValueError('Object has no modifier stack')
    return value


def modifier(value, name):
    item = value.modifiers.get(name or '')
    if item is None or item.type != 'NODES' or item.node_group is None:
        raise ValueError('modifier must name an existing Geometry Nodes modifier')
    return item


def sockets(item):
    return {s.identifier: s for s in item.node_group.interface.items_tree
            if s.item_type == 'SOCKET' and s.in_out == 'INPUT'}


def encode(value):
    if isinstance(value, bpy.types.ID):
        return {'name': value.name, 'id_type': value.id_type}
    if value is None or type(value) in (str, bool, int, float):
        return value
    return [encode(component) for component in value]


def socket_type(socket):
    kind = socket.socket_type
    # Interface subtypes (FloatFactor, VectorTranslation, etc.) share storage.
    for base in ['NodeSocketFloat', 'NodeSocketInt', 'NodeSocketVector']:
        if kind.startswith(base):
            return base
    return kind


def editable(socket):
    return socket_type(socket) in {*REFERENCES, *ARRAYS, 'NodeSocketFloat', 'NodeSocketInt',
                                    'NodeSocketBool', 'NodeSocketString'}


def inspect(params):
    value = host(params['name'])
    items = [modifier(value, params['modifier'])] if params.get('modifier') else [
        m for m in value.modifiers if m.type == 'NODES' and m.node_group]
    reports = []
    for item in items:
        store = InputStore(item)
        inputs = []
        for identifier, socket in sockets(item).items():
            attribute = identifier+'_use_attribute'
            inputs.append({'identifier': identifier, 'name': socket.name, 'socket_type': socket.socket_type,
                'editable': editable(socket), 'value': encode(store.get(identifier,
                    getattr(socket, 'default_value', None))) if editable(socket) else None,
                'minimum': getattr(socket, 'min_value', None), 'maximum': getattr(socket, 'max_value', None),
                'attribute_supported': attribute in store and not getattr(socket, 'force_non_field', False),
                'use_attribute': bool(store.get(attribute, False)),
                'attribute_name': store.get(identifier+'_attribute_name', '')})
        reports.append({'name': item.name, 'node_group': item.node_group.name,
            'nodes': len(item.node_group.nodes), 'links': len(item.node_group.links),
            'show_viewport': item.show_viewport, 'show_render': item.show_render, 'inputs': inputs})
    return {'name': value.name, 'modifiers': reports}


def numeric(value, socket):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f'{socket.identifier} requires finite numbers')
    if not getattr(socket, 'min_value', -math.inf) <= value <= getattr(socket, 'max_value', math.inf):
        raise ValueError(f'{socket.identifier} is outside its native socket range')
    return value


def decode(value, socket):
    kind = socket_type(socket)
    if kind in REFERENCES:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {'name', 'id_type'}:
            raise ValueError('Datablock inputs require {name, id_type} or null')
        pool, id_type = REFERENCES[kind]
        if value['id_type'] != id_type or not isinstance(value['name'], str):
            raise ValueError('Datablock input type does not match the socket')
        result = getattr(bpy.data, pool).get(value['name'])
        if result is None:
            raise ValueError('Referenced datablock does not exist')
        return result
    if kind in ARRAYS:
        if not isinstance(value, list) or len(value) != ARRAYS[kind]:
            raise ValueError(f'{kind} needs {ARRAYS[kind]} components')
        return [numeric(v, socket) for v in value]
    if kind == 'NodeSocketFloat':
        return float(numeric(value, socket))
    if kind == 'NodeSocketInt':
        if type(value) is not int:
            raise ValueError('Integer sockets require integers')
        return numeric(value, socket)
    if kind == 'NodeSocketBool' and type(value) is bool:
        return value
    if kind == 'NodeSocketString' and isinstance(value, str):
        return value
    raise ValueError(f'Input is not an editable value for {kind}')


def matches(actual, expected):
    if isinstance(expected, (list, tuple)):
        return len(actual) == len(expected) and all(matches(a, b) for a, b in zip(actual, expected, strict=True))
    if type(expected) is float:
        return math.isclose(actual, expected, abs_tol=1e-6, rel_tol=1e-6)
    return actual == expected


def update(value):
    value.update_tag()
    bpy.context.view_layer.update()


def set_inputs(params):
    value = host(params['name'])
    if value.library and value.override_library is None:
        raise ValueError('Linked object needs an editable local copy or library override')
    item = modifier(value, params.get('modifier'))
    store = InputStore(item)
    available = sockets(item)
    inputs, attributes = params.get('inputs', {}), params.get('attributes', {})
    if not isinstance(inputs, dict) or not isinstance(attributes, dict) or not (inputs or attributes):
        raise ValueError('Provide inputs or attributes keyed by socket identifier')
    changes = {}
    # Validate the complete edit before writing any modifier property.
    for identifier, supplied in inputs.items():
        if identifier not in available:
            raise ValueError('Unknown input socket identifier: '+str(identifier))
        changes[identifier] = decode(supplied, available[identifier])
    for identifier, attribute in attributes.items():
        key = identifier+'_use_attribute'
        if identifier not in available or key not in store or getattr(available[identifier], 'force_non_field', False):
            raise ValueError('Socket does not support named attributes: '+str(identifier))
        if attribute is not None and (not isinstance(attribute, str) or not attribute.strip()):
            raise ValueError('Attribute name must be nonempty, or null to disable it')
        changes[key] = attribute is not None
        if attribute is not None:
            changes[identifier+'_attribute_name'] = attribute
    before = {key: (key in store, store.get(key)) for key in changes}
    before = {key: (exists, old if old is None or isinstance(old, bpy.types.ID)
                           or type(old) in (str, bool, int, float) else list(old))
              for key, (exists, old) in before.items()}
    try:
        for key, changed in changes.items():
            store[key] = changed
        update(value)
        for key, expected in changes.items():
            if not matches(store.get(key), expected):
                raise ValueError('Blender changed the requested input: '+key)
    except Exception:
        for key, (existed, old) in before.items():
            if existed:
                store[key] = old
            elif key in store:
                del store[key]
        update(value)
        raise
    return inspect({'name': value.name, 'modifier': item.name})


def snapshot(params):
    value = host(params['name'])
    name = new_name(params.get('new_name'))
    if len(name.encode()) > 63:
        raise ValueError('Snapshot name must fit 63 UTF-8 bytes')
    if not any(m.type == 'NODES' and m.node_group for m in value.modifiers):
        raise ValueError('Source needs a Geometry Nodes modifier')
    depsgraph = bpy.context.evaluated_depsgraph_get()
    if any(i.is_instance and i.parent and i.parent.original == value for i in depsgraph.object_instances):
        raise ValueError('Source contains unrealized instances; realize them in the graph or export with preserve_instances')
    mesh = copy = None
    try:
        mesh = bpy.data.meshes.new_from_object(value.evaluated_get(depsgraph),
            preserve_all_data_layers=True, depsgraph=depsgraph)
        triangles = triangle_count(mesh)
        if not 0 < triangles <= MAX_TRIANGLES:
            raise ValueError(f'Snapshot must have 1 to {MAX_TRIANGLES} triangles')
        copy = bpy.data.objects.new(name, mesh)
        (value.users_collection[0] if value.users_collection else bpy.context.collection).objects.link(copy)
        copy.matrix_world = value.matrix_world.copy()
        counts = [0]*len(mesh.materials)
        for polygon in mesh.polygons:
            if polygon.material_index < len(counts):
                counts[polygon.material_index] += len(polygon.vertices)-2
        return {**info(copy), 'source': value.name, 'scope': 'evaluated_mesh_current_frame',
                'frame': bpy.context.scene.frame_current+bpy.context.scene.frame_subframe, 'triangles': triangles,
                'materials': [m.name if m else None for m in mesh.materials],
                'material_triangles': [{'slot': i, 'material': m.name if m else None, 'triangles': counts[i]}
                                       for i, m in enumerate(mesh.materials)]}
    except Exception:
        if copy:
            bpy.data.objects.remove(copy, do_unlink=True)
        if mesh and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
        raise
