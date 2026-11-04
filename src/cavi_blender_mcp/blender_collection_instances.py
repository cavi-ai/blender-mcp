"""Resolve collection definitions through an explicit instance in the current scene."""

import bpy

from .blender_bridge import obj


def root(name):
    value = obj(name)
    if value.type != 'EMPTY' or value.instance_type != 'COLLECTION' or value.instance_collection is None:
        raise ValueError('instance must name a collection-instance empty in the current scene')
    return value


def members(collection):
    pending, seen, objects = [collection], set(), set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        pending.extend(current.children)
        for value in current.objects:
            objects.add(value)
            if value.instance_type == 'COLLECTION' and value.instance_collection:
                pending.append(value.instance_collection)
    return objects


def object_in_instance(name, instance, mesh=False):
    value = bpy.data.objects.get(name)
    if value is None or value not in members(root(instance).instance_collection):
        raise ValueError('Object is not a member of the selected instance definition')
    if mesh and value.type != 'MESH':
        raise ValueError('Object must be a mesh')
    return value


def inspect(params):
    value = root(params['name'])
    collection = value.instance_collection
    offset, limit = params.get('offset', 0), params.get('limit', 200)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Use a nonnegative offset and limit from 1 to 1000')
    objects = sorted(members(collection), key=lambda v: v.name)
    users = sorted(v.name for v in bpy.context.scene.objects if v.instance_type == 'COLLECTION'
                   and v.instance_collection == collection)
    return {'name': value.name, 'instance_collection': collection.name,
            'scope': 'collection_definition', 'instance_offset': list(collection.instance_offset),
            'scene_instances': users[:1000], 'scene_instance_total': len(users),
            'scene_instances_truncated': len(users) > 1000,
            'objects': [{'name': v.name, 'type': v.type,
                         'collections': [c.name for c in v.users_collection],
                         'material_slots': [{'index': i, 'material': s.material.name if s.material else None,
                                             'link': s.link} for i, s in enumerate(v.material_slots)],
                         'modifiers': [{'name': m.name, 'type': m.type} for m in v.modifiers]}
                        for v in objects[offset:offset+limit]],
            'total': len(objects), 'offset': offset, 'limit': limit}
