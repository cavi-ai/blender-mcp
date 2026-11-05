"""Inspect and edit native shader socket defaults without rebuilding authored graphs."""

import hashlib
import math
from pathlib import Path

import bpy

from .blender_images import packed_snapshot
from .blender_materials import CONFIG_TAG
from .blender_node_inputs import encode, matches
from .blender_udim import packed_receipts, packed_tiles, tile_sources, verify_tiles

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


def socket_report(socket):
    prop = socket.bl_rna.properties.get('default_value')
    return {'identifier': socket.identifier, 'name': socket.name, 'type': socket.type,
        'editable': editable(socket), 'linked': socket.is_linked,
        'value': encode(socket.default_value) if editable(socket) else None,
        'minimum': getattr(prop, 'hard_min', None), 'maximum': getattr(prop, 'hard_max', None)}


def node_report(node):
    report = {'name': node.name, 'type': node.type,
              'inputs': [socket_report(s) for s in node.inputs],
              'outputs': [socket_report(s) for s in node.outputs]}
    if node.type == 'GROUP' and node.node_tree:
        report['group'] = node.node_tree.name
    if hasattr(node, 'image') and node.image:
        image = node.image
        report['image'] = {'name': image.name, 'source': image.source, 'path': image.filepath,
            'size': list(image.size), 'color_space': image.colorspace_settings.name,
            'decoded_depth_bits': image.depth, 'float_buffer': image.is_float,
            'alpha_mode': image.alpha_mode, 'packed': bool(image.packed_files)}
        if image.source == 'TILED':
            report['image'].update(dirty=image.is_dirty,
                tiles=[{'tile': t.number, 'label': t.label, 'size': list(t.size), 'channels': t.channels}
                       for t in image.tiles], packed_tiles=packed_receipts(image))
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


def editable_node(params):
    _material, tree = target(params)
    if tree is None or not tree.is_editable:
        raise ValueError('Shader node tree needs an editable local copy or library override')
    node = tree.nodes.get(params.get('node', ''))
    if node is None:
        raise ValueError('Shader node does not exist')
    return tree, node


def finish_edit(params, tree, changed, **fields):
    managed = [m for m in owners(tree) if m.is_editable and CONFIG_TAG in m] if changed else []
    tags = [(m, m[CONFIG_TAG], PROVENANCE_TAG in m, m.get(PROVENANCE_TAG)) for m in managed]
    try:
        for owner in managed:
            owner[PROVENANCE_TAG] = owner[CONFIG_TAG]
            del owner[CONFIG_TAG]
        return {**inspect({**params, 'offset': 0, 'limit': 1}), **fields,
                'managed_materials_detached': [m.name for m in managed]}
    except Exception:
        for owner, config, existed, provenance in tags:
            owner[CONFIG_TAG] = config
            if existed:
                owner[PROVENANCE_TAG] = provenance
            elif PROVENANCE_TAG in owner:
                del owner[PROVENANCE_TAG]
        raise


def update(tree):
    tree.update_tag()
    bpy.context.view_layer.update()


def set_inputs(params):
    tree, node = editable_node(params)
    updates = []
    for side in ['inputs', 'outputs']:
        values = params.get(side, {})
        if not isinstance(values, dict) or any(not isinstance(k, str) for k in values):
            raise ValueError('Provide nonempty inputs or outputs by native socket identifier')
        sockets = {s.identifier: s for s in getattr(node, side)}
        if not set(values) <= set(sockets):
            raise ValueError('Unknown native '+side+' socket identifier')
        updates.extend((side, sockets[key], decode(sockets[key], value)) for key, value in values.items())
    if not updates:
        raise ValueError('Provide nonempty inputs or outputs')
    before = [(side, s, encode(s.default_value)) for side, s, _ in updates]
    try:
        for _, socket, value in updates:
            socket.default_value = value
        update(tree)
        for _, socket, value in updates:
            if not matches(socket.default_value, value):
                raise ValueError('Blender changed the requested socket default')
        changed = {side: [s.identifier for direction, s, old in before
                         if side == direction and encode(s.default_value) != old]
                   for side in ['inputs', 'outputs']}
        fields = {'changed_inputs': changed['inputs']}
        if params.get('outputs'):
            fields['changed_outputs'] = changed['outputs']
        return finish_edit(params, tree, bool(changed['inputs'] or changed['outputs']), **fields)
    except Exception:
        for _, socket, value in before:
            socket.default_value = value
        update(tree)
        raise


def set_image(params, workspace):
    tree, node = editable_node(params)
    if not hasattr(node, 'image') or node.is_property_readonly('image'):
        raise ValueError('Shader node has no editable image binding')
    spec = params.get('image')
    if not isinstance(spec, dict) or set(spec)-{'path', 'color_space', 'alpha_mode', 'tiles'}:
        raise ValueError('Provide image path, color_space and optional alpha_mode')
    if any(not isinstance(spec.get(k), str) or not spec[k].strip() for k in ['path', 'color_space']):
        raise ValueError('Provide image path and explicit color_space')
    alpha = spec.get('alpha_mode', 'STRAIGHT')
    if alpha not in {'STRAIGHT', 'PREMUL', 'CHANNEL_PACKED', 'NONE'}:
        raise ValueError('Unknown native image alpha_mode')
    root = Path(workspace).resolve(strict=True)
    numbers = spec.get('tiles')
    if numbers is None:
        if '<UDIM>' in spec['path']:
            raise ValueError('UDIM patterns require explicit tiles')
        path = (root/spec['path']).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Image must be a file inside the workspace')
    else:
        path, sources = tile_sources(root, spec['path'], numbers)
    previous = node.image
    kind = 'FILE' if numbers is None else 'TILED'
    reusable = previous if (previous and previous.source == kind
        and Path(bpy.path.abspath(previous.filepath, library=previous.library)).resolve() == path
        and previous.colorspace_settings.name == spec['color_space'] and previous.alpha_mode == alpha) else None
    if numbers is None:
        image, fingerprint = packed_snapshot(path, root, reusable)
        source = {'path': path.relative_to(root).as_posix(), 'sha256': fingerprint,
                  'bytes': len(image.packed_file.data) if image.packed_file else 0}
    else:
        image, source = packed_tiles(path, sources, root, reusable)
    changed = image != previous
    try:
        if changed:
            try:
                image.colorspace_settings.name = spec['color_space']
            except TypeError as exc:
                raise ValueError('color_space is not available in the active OCIO configuration') from exc
            image.alpha_mode = alpha
        if numbers is None:
            if min(image.size) <= 0 or not image.packed_file:
                raise ValueError('Image could not be decoded and packed')
            if hashlib.sha256(image.packed_file.data).hexdigest() != fingerprint:
                raise ValueError('Packed image does not match the source snapshot')
        else:
            verify_tiles(image, source['tiles'], root)
        node.image = image
        update(tree)
        if node.image != image or image.colorspace_settings.name != spec['color_space']:
            raise ValueError('Blender changed the requested image binding')
        return finish_edit(params, tree, changed, changed_image=changed,
            previous_image=previous.name if previous else None,
            image_source=source)
    except Exception:
        try:
            node.image = previous
            update(tree)
        finally:
            if changed and image.users == 0:
                bpy.data.images.remove(image)
        raise
