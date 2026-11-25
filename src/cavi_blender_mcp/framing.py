"""Perspective camera framing that fits a bounding sphere at any scale."""

import math

MARGIN = 1.1
MIN_RADIUS = 1e-4


def fit_sphere(radius, fov_x, fov_y):
    """Return (distance, clip_start, clip_end) framing a sphere of `radius`.

    The sphere fills 1/MARGIN of the narrower field of view; both clip planes
    contain it and clip_start stays positive.
    """
    radius = max(radius, MIN_RADIUS)
    half = min(fov_x, fov_y) / 2
    distance = radius / math.sin(half) * MARGIN
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
