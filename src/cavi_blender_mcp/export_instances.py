"""Temporary data-linked material groups for FBX mesh sharing."""

from contextlib import contextmanager

import bpy


@contextmanager
def instance_meshes(objects):
    if len(set(objects)) != len(objects):
        raise ValueError("Instance export requires unique object names")
    for value in objects:
        if (
            value.library
            or value.override_library
            or value.modifiers
            or value.data.shape_keys
            or value.find_armature()
        ):
            raise ValueError(
                "Instance export requires local static meshes without modifiers, shape keys or an armature"
            )
        if any(
            face.material_index >= max(1, len(value.material_slots)) for face in value.data.polygons
        ):
            raise ValueError("Instance export found a missing material slot")
        bound = [slot.material for slot in value.material_slots]
        if any(material is None for material in bound) or len(set(bound)) != len(bound):
            raise ValueError("Instance export requires populated, distinct material slots")
    saved = [
        (value, value.data, [(slot.link, slot.material) for slot in value.material_slots])
        for value in objects
    ]
    copies = {}
    grouped_vertices = 0
    try:
        for value, original, slots in saved:
            key = (
                original.as_pointer(),
                tuple(material.as_pointer() if material else 0 for _, material in slots),
            )
            if key not in copies:
                grouped_vertices += len(original.vertices)
                if grouped_vertices > 1000000:
                    raise ValueError("Instance export is bounded to one million grouped vertices")
                copy = original.copy()
                copies[key] = copy
                for index, (_, material) in enumerate(slots):
                    copy.materials[index] = material
            value.data = copies[key]
            for slot in value.material_slots:
                slot.link = "DATA"
        bpy.context.view_layer.update()
        yield
    finally:
        for value, original, slots in saved:
            value.data = original
            for index, (link, material) in enumerate(slots):
                value.material_slots[index].link = link
                if link == "OBJECT":
                    value.material_slots[index].material = material
        for mesh in copies.values():
            bpy.data.meshes.remove(mesh)
        bpy.context.view_layer.update()
