"""Inspect and edit native shader socket defaults without rebuilding authored graphs."""

import math

import bpy

from .blender_materials import CONFIG_TAG
from .blender_node_inputs import encode, matches

PROVENANCE_TAG = 'cavi_material_config_source'


def target(params):
    material = bpy.data.materials.get(params['material_name'])
    if material is None:
        raise ValueError('Material does not exist')
    tree = material.node_tree
    path = params.get('group_path', [])
    if not isinstance(path, list) or any(not isinstance(name, str) or not name for name in path):
        raise ValueError('group_path must list exact shader group node names')
    for name in path:
        node = tree.nodes.get(name) if tree else None
        if node is None or node.type != 'GROUP' or node.node_tree is None:
            raise ValueError('Group path does not resolve to a shader node tree')
        tree = node.node_tree
    return material, tree


def editable(socket):
    if not hasattr(socket, 'default_value') or socket.is_property_readonly('default_value'):
        return False
    value = socket.default_value
    return type(value) in (str, bool, int, float) or (
        hasattr(value, '__len__') and all(type(v) in (int, float) for v in value))


def decode(socket, supplied):
    if not editable(socket):
        raise ValueError('Socket has no editable native default: '+socket.identifier)
    current = socket.default_value
    prop = socket.bl_rna.properties['default_value']

    def number(value):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError('Socket values require finite numbers')
        if not getattr(prop, 'hard_min', -math.inf) <= value <= getattr(prop, 'hard_max', math.inf):
            raise ValueError('Socket value exceeds its native range')
        return value

    if type(current) is bool and type(supplied) is bool:
        return supplied
    if type(current) is int and type(supplied) is int:
        return number(supplied)
    if type(current) is float:
        return float(number(supplied))
    if type(current) is str:
        if isinstance(supplied, str):
            return supplied
        raise ValueError('String sockets require strings')
    if hasattr(current, '__len__') and isinstance(supplied, list) and len(current) == len(supplied):
        return [number(v) for v in supplied]
    raise ValueError('Value does not match the native socket type')


def owners(tree):
    found = []
    for material in bpy.data.materials:
        pending, seen = [material.node_tree] if material.node_tree else [], set()
        while pending:
            value = pending.pop()
            if value in seen:
                continue
            seen.add(value)
            if value == tree:
                found.append(material)
                break
            pending.extend(n.node_tree for n in value.nodes if n.type == 'GROUP' and n.node_tree)
    return sorted(found, key=lambda m: m.name)


def node_report(node):
    inputs = []
    for socket in node.inputs:
        prop = socket.bl_rna.properties.get('default_value')
        inputs.append({'identifier': socket.identifier, 'name': socket.name, 'type': socket.type,
            'editable': editable(socket), 'linked': socket.is_linked,
            'value': encode(socket.default_value) if editable(socket) else None,
            'minimum': getattr(prop, 'hard_min', None), 'maximum': getattr(prop, 'hard_max', None)})
    report = {'name': node.name, 'type': node.type, 'inputs': inputs}
    if node.type == 'GROUP' and node.node_tree:
        report['group'] = node.node_tree.name
    if node.type == 'TEX_IMAGE' and node.image:
        image = node.image
        report['image'] = {'name': image.name, 'source': image.source, 'path': image.filepath,
            'size': list(image.size), 'color_space': image.colorspace_settings.name,
            'decoded_depth_bits': image.depth, 'float_buffer': image.is_float,
            'packed': bool(image.packed_file)}
    return report


def inspect(params):
    material, tree = target(params)
    offset, limit = params.get('offset', 0), params.get('limit', 100)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Use nonnegative offset and limit from 1 to 1000')
    nodes = sorted(tree.nodes, key=lambda n: n.name) if tree else []
    if params.get('node') is not None:
        node = tree.nodes.get(params['node']) if tree else None
        if node is None:
            raise ValueError('Shader node does not exist')
        nodes = [node]
    page = nodes[offset:offset+limit]
    selected = set(page)
    users = owners(tree) if tree else [material]
    return {'material': material.name, 'use_nodes': material.use_nodes, 'material_users': material.users,
        'managed_configuration': CONFIG_TAG in material, 'configuration_provenance': PROVENANCE_TAG in material,
        'node_tree': tree.name if tree else None, 'group_path': params.get('group_path', []),
        'tree_users': tree.users if tree else 0, 'affected_materials': [m.name for m in users[:1000]],
        'affected_material_total': len(users), 'affected_materials_truncated': len(users) > 1000,
        'nodes': [node_report(n) for n in page], 'total': len(nodes), 'offset': offset, 'limit': limit,
        'links': [{'from_node': l.from_node.name, 'from_socket': l.from_socket.identifier,
                   'to_node': l.to_node.name, 'to_socket': l.to_socket.identifier}
                  for l in tree.links if l.from_node in selected or l.to_node in selected] if tree else [],
        'link_scope': 'touching_returned_nodes'}


def set_inputs(params):
    _material, tree = target(params)
    if tree is None or not tree.is_editable:
        raise ValueError('Shader node tree needs an editable local copy or library override')
    node = tree.nodes.get(params.get('node', ''))
    inputs = params.get('inputs')
    if node is None or not isinstance(inputs, dict) or not inputs:
        raise ValueError('Provide a shader node and nonempty inputs')
    sockets = {s.identifier: s for s in node.inputs}
    if not set(inputs) <= set(sockets):
        raise ValueError('Unknown native input socket identifier')
    updates = [(sockets[key], decode(sockets[key], value)) for key, value in inputs.items()]
    before = [(s, encode(s.default_value)) for s, _ in updates]
    managed = [m for m in owners(tree) if m.is_editable and CONFIG_TAG in m]
    tags = [(m, m[CONFIG_TAG], PROVENANCE_TAG in m, m.get(PROVENANCE_TAG)) for m in managed]
    try:
        for socket, value in updates:
            socket.default_value = value
        tree.update_tag()
        bpy.context.view_layer.update()
        for socket, value in updates:
            if not matches(socket.default_value, value):
                raise ValueError('Blender changed the requested socket default')
        changed = [s.identifier for s, old in before if encode(s.default_value) != old]
        if not changed:
            managed = []
        for owner in managed:
            owner[PROVENANCE_TAG] = owner[CONFIG_TAG]
            del owner[CONFIG_TAG]
        return {**inspect({**params, 'offset': 0, 'limit': 1}),
                'changed_inputs': changed,
                'managed_materials_detached': [m.name for m in managed]}
    except Exception:
        for socket, value in before:
            socket.default_value = value
        for owner, config, existed, provenance in tags:
            owner[CONFIG_TAG] = config
            if existed:
                owner[PROVENANCE_TAG] = provenance
            elif PROVENANCE_TAG in owner:
                del owner[PROVENANCE_TAG]
        tree.update_tag()
        bpy.context.view_layer.update()
        raise
