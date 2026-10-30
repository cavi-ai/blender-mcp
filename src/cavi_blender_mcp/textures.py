"""Bounded PNG input receipts before native image decoding."""

import hashlib
import struct
from pathlib import Path


def read_png(workspace, name):
    root = Path(workspace).resolve(strict=True)
    path = (root / name).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Texture must be a file inside the workspace")
    if path.suffix.lower() != ".png":
        raise ValueError("Base-color texture must be a PNG")
    with path.open("rb") as stream:
        data = stream.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError("PNG exceeds 16 MiB")
    if len(data) < 29 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[8:16] != b"\0\0\0\rIHDR":
        raise ValueError("Expected a PNG with an IHDR header")
    width, height = struct.unpack(">II", data[16:24])
    if not 1 <= width <= 4096 or not 1 <= height <= 4096:
        raise ValueError("PNG dimensions must be 1 to 4096 pixels")
    return {"path": str(path), "width": width, "height": height,
            "sha256": hashlib.sha256(data).hexdigest()}, data


def png_input(workspace, name):
    return read_png(workspace, name)[0]
