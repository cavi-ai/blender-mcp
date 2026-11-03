"""Editable pose constraints and precise, transactional vertex-group assignments."""

import math

import bpy

from .blender_bridge import info, obj, vector
from .blender_rig import weights as inspect_weights
from .blender_rigging import label


def armature(name):
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Switch Blender to Object Mode before editing a rig')
    value = obj(name)
    if value.type != 'ARMATURE':
        raise ValueError('name must identify an armature')
    return value


def target(spec, prefix, rig, chain):
    name = spec.get(prefix + 'target')
    subtarget = spec.get(prefix + 'subtarget')
    if not name:
        if subtarget:
            raise ValueError('A subtarget needs its target object')
        return None
    value = obj(name)
    if subtarget:
        if value.type != 'ARMATURE' or subtarget not in value.pose.bones:
            raise ValueError(f'Target bone does not exist: {subtarget}')
        if value == rig:
            bone = value.pose.bones[subtarget]
            while bone is not None:
                if bone.name in chain:
                    raise ValueError('IK target depends on the constrained chain')
                bone = bone.parent
    return value


def add_constraint(p):
    rig = armature(p.get('name'))
    spec = p.get('constraint')
    if not isinstance(spec, dict):
        raise TypeError('constraint is required')
    name = label(spec.get('name'), 'constraint name')
    bone_name = label(spec.get('bone'), 'bone')
    bone = rig.pose.bones.get(bone_name)
    if bone is None or name in bone.constraints:
        raise ValueError('Bone is missing or constraint name already exists')
    kind = spec.get('type')
    common = {'name', 'bone', 'type', 'influence'}
    if kind == 'IK':
        allowed = common | {'target', 'subtarget', 'pole_target', 'pole_subtarget',
                            'pole_angle_degrees', 'chain_count', 'iterations',
                            'use_tail', 'use_stretch'}
        count, iterations = spec.get('chain_count', 2), spec.get('iterations', 500)
        if (type(count) is not int or not 0 <= count <= 255 or type(iterations) is not int
                or not 1 <= iterations <= 10000):
            raise ValueError('Invalid IK chain_count or iterations')
        chain, parent = [], bone
        while parent is not None and (count == 0 or len(chain) < count):
            chain.append(parent.name)
            parent = parent.parent
        destination = target(spec, '', rig, chain)
        pole = target(spec, 'pole_', rig, chain)
        if destination is None:
            raise ValueError('IK requires a target')
        angle = spec.get('pole_angle_degrees', 0)
        if type(angle) not in (int, float) or not math.isfinite(angle):
            raise ValueError('pole_angle_degrees must be finite')
        for key in ('use_tail', 'use_stretch'):
            if type(spec.get(key, True)) is not bool:
                raise ValueError(f'{key} must be boolean')
    elif kind == 'LIMIT_ROTATION':
        allowed = common | {'minimum_degrees', 'maximum_degrees', 'axes', 'owner_space'}
        minimum, maximum = vector(spec.get('minimum_degrees')), vector(spec.get('maximum_degrees'))
        axes = spec.get('axes', [True, True, True])
        if (not isinstance(axes, (list, tuple)) or len(axes) != 3
                or any(type(v) is not bool for v in axes)):
            raise ValueError('axes needs three booleans')
        if any(a > b for a, b in zip(minimum, maximum, strict=True)):
            raise ValueError('Minimum rotation must not exceed maximum')
    else:
        raise ValueError('Constraint type must be IK or LIMIT_ROTATION')
    influence = spec.get('influence', 1)
    if (type(influence) not in (int, float) or not math.isfinite(influence)
            or not 0 <= influence <= 1 or not set(spec) <= allowed):
        raise ValueError('Invalid constraint properties or influence')
    constraint = bone.constraints.new(kind)
    try:
        constraint.name, constraint.influence = name, influence
        if kind == 'IK':
            constraint.target = destination
            constraint.subtarget = spec.get('subtarget') or ''
            constraint.pole_target = pole
            constraint.pole_subtarget = spec.get('pole_subtarget') or ''
            constraint.pole_angle = math.remainder(math.radians(angle), math.tau)
            constraint.chain_count, constraint.iterations = count, iterations
            constraint.use_tail = spec.get('use_tail', True)
            constraint.use_stretch = spec.get('use_stretch', True)
        else:
            constraint.owner_space = spec.get('owner_space', 'LOCAL')
            for axis, enabled, low, high in zip('xyz', axes, minimum, maximum, strict=True):
                low, high = math.radians(low), math.radians(high)
                prop = constraint.bl_rna.properties['min_' + axis]
                if not prop.hard_min <= low <= high <= prop.hard_max:
                    raise ValueError('Rotation limit exceeds the native Blender range')
                setattr(constraint, 'min_' + axis, low)
                setattr(constraint, 'max_' + axis, high)
                setattr(constraint, 'use_limit_' + axis, enabled)
        bpy.context.view_layer.update()
    except Exception:
        bone.constraints.remove(constraint)
        raise
    return {**info(rig), 'bone': bone_name, 'constraint': name, 'constraint_type': kind,
            'influence': constraint.influence}


def remove_constraint(p):
    rig = armature(p.get('name'))
    bone = rig.pose.bones.get(label(p.get('bone'), 'bone'))
    name = label(p.get('constraint_name'), 'constraint_name')
    if bone is None or name not in bone.constraints:
        raise ValueError('Constraint does not exist on the named bone')
    bone.constraints.remove(bone.constraints[name])
    bpy.context.view_layer.update()
    return {**info(rig), 'bone': bone.name, 'removed_constraint': name}


def assign_weights(p):
    mesh = obj(p.get('name'), mesh=True)
    if bpy.context.mode != 'OBJECT' or mesh.data.users != 1:
        raise ValueError('Exact skin weighting needs Object Mode and single-user mesh data')
    modifiers = [m for m in mesh.modifiers if m.type == 'ARMATURE' and m.object is not None]
    if len(modifiers) != 1:
        raise ValueError('Skin must have exactly one bound armature modifier')
    rig = modifiers[0].object
    deform = {b.name for b in rig.data.bones if b.use_deform}
    specs = p.get('vertex_weights')
    replace, normalize = p.get('replace', True), p.get('normalize', False)
    if type(replace) is not bool or type(normalize) is not bool:
        raise ValueError('replace and normalize must be boolean')
    if not isinstance(specs, list) or not 1 <= len(specs) <= 100000:
        raise ValueError('vertex_weights needs 1..100000 assignments')
    parsed, seen = [], set()
    for spec in specs:
        if not isinstance(spec, dict) or set(spec) != {'vertex', 'weights'}:
            raise ValueError('Each assignment needs vertex and weights')
        index, values = spec['vertex'], spec['weights']
        if (type(index) is not int or not 0 <= index < len(mesh.data.vertices)
                or index in seen):
            raise ValueError('Vertex indices must exist and must not repeat')
        if not isinstance(values, dict) or not set(values) <= deform:
            raise ValueError('Weights must name deform bones on the bound armature')
        if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
               for v in values.values()):
            raise ValueError('Skin weights must be finite values in 0..1')
        seen.add(index)
        parsed.append((index, values))
    names = {g.index: g.name for g in mesh.vertex_groups}
    before = {i: {names[g.group]: g.weight for g in mesh.data.vertices[i].groups
                  if names[g.group] in deform} for i, _ in parsed}
    original_groups = set(names.values())

    def write(index, values):
        for group in mesh.vertex_groups:
            if group.name in deform:
                group.remove([index])
        for name, value in values.items():
            if value:
                group = mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
                group.add([index], value, 'REPLACE')

    try:
        for index, values in parsed:
            desired = {} if replace else dict(before[index])
            desired.update(values)
            total = math.fsum(desired.values())
            if normalize and total:
                desired = {key: value/total for key, value in desired.items()}
            write(index, desired)
    except Exception:
        for index, values in before.items():
            write(index, values)
        for group in list(mesh.vertex_groups):
            if group.name not in original_groups:
                mesh.vertex_groups.remove(group)
        raise
    mesh.data.update()
    return {**info(mesh), 'armature': rig.name, 'assigned_vertices': len(parsed),
            'weights': inspect_weights(mesh, deform, max(1, len(deform)))}


HANDLERS = {'add_constraint': add_constraint, 'remove_constraint': remove_constraint,
            'assign_weights': assign_weights}
