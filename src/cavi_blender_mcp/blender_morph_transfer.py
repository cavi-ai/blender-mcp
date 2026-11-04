"""Selected relative shape deltas on an existing rest-surface projection."""

import math

import numpy as np

from .blender_rigging import MAX_ASSIGNMENTS, label
from .blender_shape_keys import MAX_KEYS


def coordinates(values):
    result = np.empty(len(values)*3, dtype=np.float64)
    values.foreach_get('co', result)
    result = result.reshape(-1, 3)
    if not np.isfinite(result).all():
        raise ValueError('Transferred shape coordinates must be finite')
    return result


def prepare(source, target, names, projection):
    if not names:
        return []
    if len(names)*(len(source.data.vertices)+len(target.data.vertices)) > MAX_ASSIGNMENTS:
        raise ValueError('Morph transfer exceeds one million source/target vertex samples')
    source_keys, target_keys = source.data.shape_keys, target.data.shape_keys
    if source_keys is None or not source_keys.use_relative or (target_keys and not target_keys.use_relative):
        raise ValueError('Selected morph transfer needs relative source and target shape keys')
    existing = set(target_keys.key_blocks.keys()) if target_keys else {'Basis'}
    if len(existing)+len(names) > MAX_KEYS:
        raise ValueError(f'Transferred copy exceeds {MAX_KEYS} shape keys including Basis')
    if any(name in existing or name not in source_keys.key_blocks
           or name == source_keys.key_blocks[0].name for name in names):
        raise ValueError('Selected morphs must exist beyond Basis and have unused target names')
    indices = np.asarray([triangle for triangle, _ in projection], dtype=np.int32)
    factors = np.asarray([weights for _, weights in projection], dtype=np.float64)
    to_world = np.asarray(source.matrix_world, dtype=np.float64)[:3, :3]
    to_target = np.linalg.inv(np.asarray(target.matrix_world, dtype=np.float64)[:3, :3])
    target_basis = coordinates(target_keys.key_blocks[0].data if target_keys else target.data.vertices)
    result = []
    for name in names:
        label(name, 'shape name')
        block = source_keys.key_blocks[name]
        delta = coordinates(block.data) - coordinates(block.relative_key.data)
        if block.vertex_group:
            group = source.vertex_groups.get(block.vertex_group)
            if group is None:
                raise ValueError('Source shape mask names a missing vertex group')
            mask = np.asarray([next((item.weight for item in vertex.groups
                               if item.group == group.index), 0.) for vertex in source.data.vertices])
            if not np.isfinite(mask).all() or np.any((mask < 0) | (mask > 1)):
                raise ValueError('Source shape mask weights must be finite in 0..1')
            delta *= mask[:, None]
        projected = np.einsum('ij,ijk->ik', factors, delta[indices])
        world = projected @ to_world.T
        delta = world @ to_target.T
        coordinates_out = target_basis + delta
        if (not np.isfinite(coordinates_out).all()
                or np.any(np.abs(coordinates_out) > np.finfo(np.float32).max)):
            raise ValueError('Transferred morph coordinates exceed native mesh precision')
        maximum = float(np.linalg.norm(world, axis=1).max())
        result.append({'source': block, 'delta': delta, 'max_world_delta': maximum})
    return result


def apply(copy, source, prepared, meters):
    if not prepared:
        return []
    if copy.data.shape_keys is None:
        copy.shape_key_add(name='Basis', from_mix=False)
    keys = copy.data.shape_keys
    basis = coordinates(keys.key_blocks[0].data)
    result = []
    for item in prepared:
        donor = item['source']
        block = copy.shape_key_add(name=donor.name, from_mix=False)
        block.relative_key = keys.key_blocks[0]
        block.slider_min, block.slider_max = donor.slider_min, donor.slider_max
        block.data.foreach_set('co', (basis + item['delta']).reshape(-1))
        driver = block.driver_add('value').driver
        driver.type = 'SCRIPTED'
        for name, path in (('source_value', 'value'), ('source_mute', 'mute')):
            variable = driver.variables.new()
            variable.name, variable.type = name, 'SINGLE_PROP'
            binding = variable.targets[0]
            binding.id_type, binding.id = 'KEY', source.data.shape_keys
            binding.data_path = donor.path_from_id(path)
        driver.expression = 'source_value*(1-source_mute)'
        result.append({'name': block.name, 'source_relative_key': donor.relative_key.name,
                       'source_mask': donor.vertex_group, 'driven_from': source.name,
                       'max_delta_m': item['max_world_delta']*meters})
    if any(not math.isfinite(item['max_delta_m']) for item in result):
        raise ValueError('Transferred morph metre deltas must be finite')
    return result
