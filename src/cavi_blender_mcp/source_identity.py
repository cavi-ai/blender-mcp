"""Retain saved-source identity at load/save boundaries rather than trusting current disk bytes."""
import hashlib
import os
from pathlib import Path


class LoadedSource:
    def __init__(self):
        self.source = None

    def capture(self, path):
        self.source = None
        if not path:
            return
        try:
            location = Path(path).resolve(strict=True)
            with location.open('rb') as stream:
                before = os.fstat(stream.fileno())
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                after = os.fstat(stream.fileno())
            def signature(value):
                return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns
            if signature(before) == signature(after) == signature(location.stat()):
                self.source = {'path': str(location), 'sha256': digest, 'bytes': after.st_size}
        except OSError:
            return

    def inspect(self, path, dirty):
        same_path = self.source is not None and str(Path(path).resolve()) == self.source['path']
        return {'saved_source': dict(self.source) if same_path else None, 'dirty': bool(dirty)}
