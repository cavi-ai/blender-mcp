"""Temporary neutral lighting for bounded Eevee material previews."""

from contextlib import contextmanager

import bpy
from mathutils import Vector


@contextmanager
def studio(scene, center, radius, floor_z):
    original_world = scene.world
    existing_lights = [(value, value.hide_render) for value in scene.objects if value.type == "LIGHT"]
    objects, lights = [], []
    world = bpy.data.worlds.new("MCP Studio")
    mesh = material = None
    try:
        for value, _ in existing_lights:
            value.hide_render = True
        world.use_nodes = True
        background = world.node_tree.nodes.get("Background")
        background.inputs["Color"].default_value = (.055, .045, .075, 1)
        background.inputs["Strength"].default_value = .45
        scene.world = world
        distance = max(radius, .5)
        for label, direction, energy, color in (
            ("Key", (3, -4, 5), 850, (1, .92, .8)),
            ("Fill", (-3, -1, 2), 300, (.8, .9, 1)),
            ("Rim", (2, 3, 4), 1000, (1, .85, .65)),
        ):
            data = bpy.data.lights.new("MCP " + label, "AREA")
            lights.append(data)
            data.energy = min(50000, energy * distance * distance)
            data.color = color
            data.shape = "DISK"
            data.size = distance * 3
            data.use_shadow = label == "Key"
            value = bpy.data.objects.new("MCP " + label, data)
            objects.append(value)
            scene.collection.objects.link(value)
            value.location = center + Vector(direction) * distance
            value.rotation_euler = (center - value.location).to_track_quat("-Z", "Y").to_euler()
        extent = max(radius * 6, 2)
        mesh = bpy.data.meshes.new("MCP Floor")
        mesh.from_pydata([(-extent, -extent, 0), (extent, -extent, 0),
                          (extent, extent, 0), (-extent, extent, 0)], [], [(0, 1, 2, 3)])
        floor = bpy.data.objects.new("MCP Floor", mesh)
        objects.append(floor)
        scene.collection.objects.link(floor)
        floor.location = (center.x, center.y, floor_z - max(radius * .005, .001))
        material = bpy.data.materials.new("MCP Floor")
        material.use_nodes = True
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Base Color"].default_value = (.028, .022, .04, 1)
        shader.inputs["Roughness"].default_value = .8
        mesh.materials.append(material)
        yield
    finally:
        scene.world = original_world
        for value, hidden in existing_lights:
            value.hide_render = hidden
        for value in objects:
            bpy.data.objects.remove(value, do_unlink=True)
        for data in lights:
            bpy.data.lights.remove(data)
        if mesh is not None:
            bpy.data.meshes.remove(mesh)
        if material is not None:
            bpy.data.materials.remove(material)
        bpy.data.worlds.remove(world)
