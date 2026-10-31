"""Bounded image input receipts before native image decoding."""

import hashlib
from pathlib import Path

from .importing import image_size

MAX_BYTES = 16 * 1024 * 1024
ALLOWED = {".png", ".jpg", ".jpeg"}


def _read(workspace, name, allowed):
    root = Path(workspace).resolve(strict=True)
    try:
        path = (root / name).resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError("Texture does not exist inside the workspace") from exc
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Texture must be a file inside the workspace")
    suffix = path.suffix.lower()
    if suffix not in allowed:
        raise ValueError(f"Texture must be one of {sorted(allowed)}")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("Texture exceeds 16 MiB")
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
