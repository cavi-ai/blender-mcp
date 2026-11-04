"""Bake evaluated bone motion onto an independent rig and optional skin copies."""

import math

import bpy
from mathutils import Matrix

from .blender_animation import ACTION_TAG, frame_number
from .blender_bridge import info, new_name, obj
from .blender_errors import preflight
from .blender_rig_controls import armature
from .blender_rigging import label


def matrix_error(left, right):
    return max(abs(left[r][c]-right[r][c]) for r in range(4) for c in range(4))


def transform(value, matrix, previous, key):
    location, rotation, scale = matrix.decompose()
    if matrix_error(matrix, Matrix.LocRotScale(location, rotation, scale)) > 1e-5:
        raise ValueError('Evaluated object shear cannot be represented by transform keyframes')
    if key in previous and previous[key].dot(rotation) < 0:
        rotation.negate()
    previous[key] = rotation.copy()
    value.location, value.rotation_quaternion, value.scale = location, rotation, scale


def key_transform(value, frame):
    for path in ('location', 'rotation_quaternion', 'scale'):
        if not value.keyframe_insert(path, frame=frame):
            raise RuntimeError(f'Could not key {value.name} {path}')


def linear(action):
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip, 'channelbags', ()):
                for curve in bag.fcurves:
                    for point in curve.keyframe_points:
                        point.interpolation = 'LINEAR'


def bake(p):
    with preflight():
        source = armature(p.get('name'))
        name = new_name(p.get('new_name'))
        action_name = label(p.get('action_name'), 'action_name')
        if action_name in bpy.data.actions:
            raise ValueError('Baked action name already exists')
        start, end = frame_number(p.get('start_frame')), frame_number(p.get('end_frame'))
        step = p.get('frame_step', 1)
        if start > end or isinstance(step, bool) or not isinstance(step, (int, float)) or not math.isfinite(step) or not 0 < step <= 10000:
            raise ValueError('Invalid bake frame range or frame_step')
        intervals = (end-start)/step
        if not math.isfinite(intervals) or intervals > 4095:
            raise ValueError('Bake exceeds 4096 samples')
        count = math.floor(intervals) + 1
        frames = [start + index * step for index in range(count)]
        if abs(frames[-1]-end) > 1e-8:
            frames.append(end)
        else:
            frames[-1] = float(end)
        if len(frames) > 4096 or len(frames) * len(source.pose.bones) > 1000000:
            raise ValueError('Bake exceeds 4096 samples or one million bone poses')
        names = p.get('names') or []
        if not isinstance(names, list) or len(names) > 16 or len(set(names)) != len(names):
            raise ValueError('names must contain up to 16 unique skins')
        skins, skin_names = [], []
        for index, mesh_name in enumerate(names, 1):
            mesh = obj(mesh_name, mesh=True)
            modifiers = [m for m in mesh.modifiers if m.type == 'ARMATURE']
            if len(modifiers) != 1 or modifiers[0].object != source:
                raise ValueError('Each skin needs one armature modifier bound to the source rig')
            skins.append(mesh)
            skin_names.append(new_name(f'{name}_Skin{index}'))
    scene = bpy.context.scene
    old_frame, old_subframe = scene.frame_current, scene.frame_subframe
    objects, mesh_data, rig_data, actions = [], [], [], []
    previous = {}
    maximum = 0
    try:
        rig = source.copy()
        objects.append(rig)
        rig.data = source.data.copy()
        rig_data.append(rig.data)
        rig.data.animation_data_clear()
        rig.animation_data_clear()
        rig.name = name
        rig.parent = None
        for constraint in list(rig.constraints):
            rig.constraints.remove(constraint)
        for bone in rig.pose.bones:
            bone.rotation_mode = 'QUATERNION'
            for constraint in list(bone.constraints):
                bone.constraints.remove(constraint)
        scene.collection.objects.link(rig)
        rig.rotation_mode = 'QUATERNION'
        rig.animation_data_create()
        action = bpy.data.actions.new(action_name)
        actions.append(action)
        action.use_fake_user = True
        action[ACTION_TAG] = rig.name
        action.use_frame_range = True
        action.frame_start, action.frame_end = start, end
        rig.animation_data.action = action
        rig.animation_data.action_slot = action.slots.new('OBJECT', rig.name)
        copies = []
        for mesh, mesh_name in zip(skins, skin_names, strict=True):
            copy = mesh.copy()
            objects.append(copy)
            copy.data = mesh.data.copy()
            mesh_data.append(copy.data)
            copy.name = mesh_name
            copy.animation_data_clear()
            copy.parent = rig
            copy.matrix_parent_inverse = Matrix.Identity(4)
            copy.rotation_mode = 'QUATERNION'
            copy.animation_data_create()
            copy.animation_data.action = action
            copy.animation_data.action_slot = action.slots.new('OBJECT', copy.name)
            keys = copy.data.shape_keys
            if keys is not None:
                if keys == mesh.data.shape_keys:
                    raise ValueError('Bake copy shares source shape-key data')
                keys.animation_data_clear()
                keys.animation_data_create()
                keys.animation_data.action = action
                keys.animation_data.action_slot = action.slots.new('KEY', keys.name)
            for constraint in list(copy.constraints):
                copy.constraints.remove(constraint)
            next(m for m in copy.modifiers if m.type == 'ARMATURE').object = rig
            scene.collection.objects.link(copy)
            copies.append(copy)
        ordered = sorted(rig.pose.bones, key=lambda b: len(b.parent_recursive))
        for frame in frames:
            scene.frame_set(math.floor(frame), subframe=frame % 1)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated = source.evaluated_get(depsgraph)
            world = evaluated.matrix_world.copy()
            matrices = {b.name: b.matrix.copy() for b in evaluated.pose.bones}
            skin_worlds = [mesh.evaluated_get(depsgraph).matrix_world.copy() for mesh in skins]
            shape_states = []
            for mesh in skins:
                keys = mesh.data.shape_keys
                evaluated_keys = keys.evaluated_get(depsgraph) if keys is not None else None
                shape_states.append(None if evaluated_keys is None else {
                    'relative': evaluated_keys.use_relative, 'time': evaluated_keys.eval_time,
                    'values': {key.name: key.value for key in evaluated_keys.key_blocks[1:]}})
            transform(rig, world, previous, ('object', rig.name))
            key_transform(rig, frame)
            for bone in ordered:
                bone.matrix = matrices[bone.name]
                key = ('bone', bone.name)
                if key in previous and previous[key].dot(bone.rotation_quaternion) < 0:
                    bone.rotation_quaternion.negate()
                previous[key] = bone.rotation_quaternion.copy()
                key_transform(bone, frame)
                bpy.context.view_layer.update()
            for copy, matrix, shapes in zip(copies, skin_worlds, shape_states, strict=True):
                transform(copy, world.inverted() @ matrix, previous, ('object', copy.name))
                key_transform(copy, frame)
                if shapes is not None:
                    keys = copy.data.shape_keys
                    if shapes['relative']:
                        for key_name, value in shapes['values'].items():
                            if not math.isfinite(value):
                                raise ValueError('Evaluated shape weights must be finite')
                            key = keys.key_blocks[key_name]
                            key.value = value
                            key.keyframe_insert('value', frame=frame)
                    else:
                        if not math.isfinite(shapes['time']):
                            raise ValueError('Evaluated shape time must be finite')
                        keys.eval_time = shapes['time']
                        keys.keyframe_insert('eval_time', frame=frame)
                mesh_action = copy.animation_data.action
                if mesh_action not in actions:
                    actions.append(mesh_action)
            bpy.context.view_layer.update()
            baked = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
            maximum = max(maximum, matrix_error(baked.matrix_world, world),
                          max((matrix_error(baked.pose.bones[n].matrix, m)
                               for n, m in matrices.items()), default=0))
            if maximum > 1e-4:
                raise ValueError('Baked pose differs from the evaluated source; copies removed')
        for value in actions:
            linear(value)
    except Exception:
        for value in reversed(objects):
            bpy.data.objects.remove(value, do_unlink=True)
        for value in mesh_data:
            if value.users == 0:
                bpy.data.meshes.remove(value)
        for value in rig_data:
            if value.users == 0:
                bpy.data.armatures.remove(value)
        for value in actions:
            bpy.data.actions.remove(value, do_unlink=True)
        raise
    finally:
        scene.frame_set(old_frame, subframe=old_subframe)
    return {**info(rig), 'source': source.name, 'action': action.name,
            'frame_range': [start, end], 'frames': frames,
            'maximum_matrix_component_error': maximum,
            'skins': [{'source': mesh.name, 'name': copy.name}
                      for mesh, copy in zip(skins, copies, strict=True)],
            'constraints_removed_from_copy': True,
            'shape_keys_baked': [copy.name for copy in copies if copy.data.shape_keys is not None]}
