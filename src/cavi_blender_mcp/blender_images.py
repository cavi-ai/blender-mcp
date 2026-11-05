"""Pack exact native image snapshots without changing shared image datablocks."""

import hashlib
import os
import tempfile
from pathlib import Path

import bpy


def packed_snapshot(path, workspace, existing=None, tag='cavi_source_sha256'):
    """Pack a hashed snapshot, avoiding stale/dirty images cached at the source path."""
    digest = hashlib.sha256()
    fd, name = tempfile.mkstemp(prefix='.cavi-image-', suffix=path.suffix, dir=workspace)
    snapshot = Path(name)
    try:
        with os.fdopen(fd, 'wb') as output, path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024*1024), b''):
                output.write(chunk)
                digest.update(chunk)
        fingerprint = digest.hexdigest()
        if (existing is not None and not existing.is_dirty and existing.packed_file
                and existing.get(tag) == fingerprint
                and hashlib.sha256(existing.packed_file.data).hexdigest() == fingerprint):
            return existing, fingerprint
        image = bpy.data.images.load(str(snapshot), check_existing=False)
        try:
            image.pack()
            image.filepath_raw = str(path)
            image.name = path.stem
            image[tag] = fingerprint
        except Exception:
            bpy.data.images.remove(image)
            raise
        return image, fingerprint
    finally:
        snapshot.unlink(missing_ok=True)
