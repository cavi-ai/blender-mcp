"""Small rigged, absolute-key, static and shared sources with independent save observers."""
import json
import os
import runpy
from pathlib import Path

import bpy

runpy.run_path(str(Path(__file__).with_name('uv_density_fixture.py')))
root = Path(os.environ['CAVI_BLENDER_WORKSPACE'])
source = bpy.data.objects['TileGrid']
lift = source.data.shape_keys.key_blocks['Lift']
detail = source.shape_key_add(name='Detail', from_mix=False)
detail.relative_key = lift
detail.data[0].co.z = .35
detail.value = .2
lift.keyframe_insert('value',frame=1)
lift.value = .75
lift.keyframe_insert('value',frame=11)
lift.value = .5
for name in ('Absolute','Static','SharedA'):
    value = source.copy()
    value.data = source.data.copy()
    value.name = name
    bpy.context.scene.collection.objects.link(value)
    if name == 'Absolute':
        value.data.shape_keys.use_relative = False
        value.data.shape_keys.eval_time = 5
    if name == 'Static':
        value.shape_key_clear()
        value.modifiers.clear()
shared = bpy.data.objects['SharedA'].copy()
shared.name = 'SharedB'
bpy.context.scene.collection.objects.link(shared)


def positions(obj):
    bpy.context.view_layer.update()
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    return [list(v.co) for v in evaluated.data.vertices]


def probes(obj):
    keys = obj.data.shape_keys
    if keys is None:
        return {'static': positions(obj)}
    bone = bpy.data.objects['Skeleton'].pose.bones['Root']
    original_angle, original_time = bone.rotation_euler.z, keys.eval_time
    original_values = [k.value for k in keys.key_blocks]
    animation = keys.animation_data
    action = animation.action if animation else None
    slot = animation.action_slot if animation else None
    result = {}
    try:
        if action:
            animation.action = None
        for angle in (0, .3):
            bone.rotation_euler.z = angle
            for expression in range(3):
                if keys.use_relative:
                    keys.key_blocks['Lift'].value = 1. if expression == 1 else 0.
                    keys.key_blocks['Detail'].value = 1. if expression == 2 else 0.
                else:
                    keys.eval_time = expression*10
                result[f'{angle}/{expression}'] = positions(obj)
    finally:
        bone.rotation_euler.z = original_angle
        keys.eval_time = original_time
        for k,value in zip(keys.key_blocks, original_values, strict=True):
            k.value = value
        if action:
            animation.action = action
            if slot:
                animation.action_slot = slot
        bpy.context.view_layer.update()
    return result


def animation_state(keys):
    animation = keys.animation_data if keys else None
    action = animation.action if animation else None
    if action is None:
        return None
    curves = []
    for layer in action.layers:
        for strip in layer.strips:
            for bag in getattr(strip,'channelbags',()):
                curves += [(f.data_path,f.array_index,[(list(k.co),k.interpolation) for k in f.keyframe_points])
                           for f in bag.fcurves]
    return {'action':action.name,'slot':animation.action_slot.identifier,'curves':curves}


@bpy.app.handlers.persistent
def audit_vertices(*_):
    objects = {}
    for name in ('TileGrid','Absolute','Static','SharedA','SharedB'):
        obj = bpy.data.objects[name]
        mesh, keys = obj.data, obj.data.shape_keys
        objects[name] = {
            'vertices': [list(v.co) for v in mesh.vertices],
            'faces': [list(f.vertices) for f in mesh.polygons],
            'edges': [list(e.vertices) for e in mesh.edges],
            'seams': [e.use_seam for e in mesh.edges],
            'uvs': {l.name:[list(p.uv) for p in l.data] for l in mesh.uv_layers},
            'pins': {l.name:[p.pin_uv for p in l.data] for l in mesh.uv_layers},
            'colors': [list(p.color) for p in mesh.color_attributes['Tint'].data],
            'slots': [f.material_index for f in mesh.polygons],
            'materials': [slot.material.name for slot in obj.material_slots],
            'weights': [[(g.group,g.weight) for g in v.groups] for v in mesh.vertices],
            'groups': [g.name for g in obj.vertex_groups],
            'modifiers': [(m.name,m.type,m.object.name) for m in obj.modifiers],
            'transform': [*obj.location,*obj.rotation_euler,*obj.scale],
            'parent': obj.parent.name if obj.parent else None,
            'active_shape_key': obj.active_shape_key_index,
            'key_mode': keys.use_relative if keys else None,
            'key_time': keys.eval_time if keys else None,
            'animation': animation_state(keys),
            'keys': {k.name:{'points':[list(p.co) for p in k.data], 'value':k.value,
                            'relative':k.relative_key.name,'frame':k.frame}
                     for k in keys.key_blocks} if keys else {},
            'deformed': probes(obj)}
    rig = bpy.data.objects['Skeleton']
    result = {'objects':objects,'rig':[(b.name,list(b.head_local),list(b.tail_local)) for b in rig.data.bones],
        'pose':[(b.name,list(b.rotation_euler),list(b.location),list(b.scale)) for b in rig.pose.bones],
        'selected':sorted(o.name for o in bpy.context.selected_objects),
        'active':bpy.context.view_layer.objects.active.name, 'mode':bpy.context.mode}
    (root/'vertex-audit.json').write_text(json.dumps(result))


bpy.app.handlers.save_post.append(audit_vertices)
bpy.app.handlers.load_post.append(audit_vertices)
bpy.ops.wm.save_as_mainfile(filepath=str(root/'initial.blend'),check_existing=False)
