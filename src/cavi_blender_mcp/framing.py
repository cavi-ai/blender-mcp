"""Perspective camera framing that fits a bounding sphere at any scale."""

import math

MARGIN = 1.1
MIN_RADIUS = 1e-4


def fit_sphere(radius, fov_x, fov_y, *, minimum_distance=0):
    """Return (distance, clip_start, clip_end) framing a sphere of `radius`.

    The narrower field of view sets the distance unless a farther minimum
    is requested. Both clip planes contain the sphere.
    """
    radius = max(radius, MIN_RADIUS)
    half = min(fov_x, fov_y) / 2
    distance = max(radius / math.sin(half) * MARGIN, minimum_distance)
    clip_start = min(0.1, (distance - radius) * 0.5)
    return distance, clip_start, distance + radius * 2


def effective_fov(lens, sensor_width, sensor_height, sensor_fit, width, height):
    """Return (fov_x, fov_y) in radians following Blender's sensor-fit rule."""
    if sensor_fit == "VERTICAL":
        fov_y = 2 * math.atan(sensor_height / 2 / lens)
        return 2 * math.atan(math.tan(fov_y / 2) * width / height), fov_y
    if sensor_fit == "HORIZONTAL" or width >= height:
        fov_x = 2 * math.atan(sensor_width / 2 / lens)
        return fov_x, 2 * math.atan(math.tan(fov_x / 2) * height / width)
    fov_y = 2 * math.atan(sensor_width / 2 / lens)
    return 2 * math.atan(math.tan(fov_y / 2) * width / height), fov_y


def fit_perspective(camera, render, radius, meshes):
    fov = effective_fov(camera.lens, camera.sensor_width, camera.sensor_height,
                        camera.sensor_fit, render.resolution_x * render.pixel_aspect_x,
                        render.resolution_y * render.pixel_aspect_y)
    # Viewport bounds can omit render-time geometry. Keep the previous framing
    # distance as a floor when the modifier stacks differ.
    minimum_distance = 0
    if any(modifier.show_viewport != modifier.show_render
           for mesh in meshes for modifier in mesh.modifiers):
        minimum_distance = max(radius * 3.5, 2)
    return fit_sphere(radius, *fov, minimum_distance=minimum_distance)
