"""Explicit native tiled images with exact source snapshots and per-tile receipts."""

import hashlib
import json
import tempfile
from pathlib import Path

import bpy

from .blender_images import copy_source

MANIFEST_TAG = 'cavi_udim_manifest_sha256'


def tile_sources(root, name, numbers):
    if (not isinstance(numbers, list) or not numbers
            or any(type(n) is not int or n < 1001 for n in numbers)
            or len(set(numbers)) != len(numbers)):
        raise ValueError('tiles must contain unique integer UDIM numbers from 1001')
    pattern = (root/name).resolve()
    if (name.count('<UDIM>') != 1 or '<UDIM>' not in pattern.name
            or not pattern.is_relative_to(root) or not pattern.parent.is_dir()):
        raise ValueError('UDIM path needs one <UDIM> token in a workspace filename')
    sources = []
    for number in sorted(numbers):
        path = Path(str(pattern).replace('<UDIM>', str(number)))
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise ValueError('Every UDIM tile must be a file inside the workspace')
        sources.append((number, path, resolved))
    return pattern, sources


def packed_receipts(image):
    return sorted([{'tile': p.tile_number, 'path': p.filepath,
                    'bytes': len(p.packed_file.data),
                    'sha256': hashlib.sha256(p.packed_file.data).hexdigest()}
                   for p in image.packed_files], key=lambda item: (item['tile'], item['path']))


def verify_tiles(image, items, root):
    expected = [{**item, 'path': str(root/item['path'])} for item in items]
    if ({t.number for t in image.tiles} != {item['tile'] for item in items}
            or any(min(t.size) <= 0 for t in image.tiles)
            or packed_receipts(image) != expected):
        raise ValueError('Native UDIM tiles or packed bytes do not match the declared sources')


def packed_tiles(pattern, sources, root, existing=None):
    image = None
    with tempfile.TemporaryDirectory(prefix='.cavi-udim-', dir=root) as folder:
        directory = Path(folder)
        ending = pattern.name.split('<UDIM>', 1)[1]
        snapshot = directory/('tile.<UDIM>'+ending)
        items = []
        for number, source, resolved in sources:
            target = Path(str(snapshot).replace('<UDIM>', str(number)))
            with target.open('wb') as output:
                fingerprint, count = copy_source(resolved, output)
            items.append({'tile': number, 'path': source.relative_to(root).as_posix(),
                          'bytes': count, 'sha256': fingerprint})
        manifest = hashlib.sha256(json.dumps(items, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        receipt = {'path': pattern.relative_to(root).as_posix(), 'manifest_sha256': manifest,
                   'bytes': sum(i['bytes'] for i in items), 'tiles': items, 'tile_count': len(items)}
        if (existing is not None and not existing.is_dirty and existing.get(MANIFEST_TAG) == manifest):
            try:
                verify_tiles(existing, items, root)
            except ValueError:
                pass
            else:
                return existing, receipt
        try:
            first = str(snapshot).replace('<UDIM>', str(items[0]['tile']))
            image = bpy.data.images.load(first, check_existing=False)
            image.source = 'TILED'
            image.filepath = str(snapshot)
            image.reload()
            if {t.number for t in image.tiles} != {i['tile'] for i in items}:
                raise ValueError('Blender did not load exactly the declared UDIM tiles')
            image.pack()
            locations = {i['tile']: str(root/i['path']) for i in items}
            for packed in image.packed_files:
                packed.filepath = locations[packed.tile_number]
            image.filepath_raw = str(pattern)
            if image.filepath != str(pattern):
                raise ValueError('Blender changed the requested UDIM path')
            image.name = pattern.name
            image[MANIFEST_TAG] = manifest
            verify_tiles(image, items, root)
            return image, receipt
        except Exception:
            if image is not None:
                bpy.data.images.remove(image)
            raise
