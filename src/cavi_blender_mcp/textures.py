"""Bounded image input receipts before native image decoding."""

import hashlib

from .importing import image_size, workspace_bytes

MAX_BYTES = 16 * 1024 * 1024
ALLOWED = {".png", ".jpg", ".jpeg"}


def _read(workspace, name, allowed):
    path, data = workspace_bytes(workspace, name, allowed, "Texture", MAX_BYTES)
    suffix = path.suffix.lower()
    width, height = image_size(data)
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError("Texture dimensions must be 1 to 4096 pixels")
    return {
        "path": str(path),
        "format": suffix.lstrip("."),
        "width": width,
        "height": height,
        "pixels": width * height,
        "sha256": hashlib.sha256(data).hexdigest(),
    }, data


def read_image(workspace, name):
    return _read(workspace, name, ALLOWED)


def read_png(workspace, name):
    return _read(workspace, name, {".png"})


def png_input(workspace, name):
    return read_png(workspace, name)[0]


def image_input(workspace, name):
    return read_image(workspace, name)[0]
