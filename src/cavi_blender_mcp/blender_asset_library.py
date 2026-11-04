"""Native Blender library catalogs and independent appends with source identity."""

import hashlib
import json
from pathlib import Path

import bpy

KINDS = {'objects': ('Object', 'OBJECT'), 'collections': ('Collection', 'COLLECTION'),
         'materials': ('Material', 'MATERIAL'), 'node_groups': ('NodeTree', 'NODETREE')}


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def source(workspace, name):
    root = Path(workspace).resolve(strict=True)
    if not isinstance(name, str) or Path(name).is_absolute():
        raise ValueError('Library path must be relative to the workspace')
    path = (root/name).resolve(strict=True)
    if not path.is_relative_to(root) or path.suffix.lower() != '.blend' or not path.is_file():
        raise ValueError('Library must be a workspace .blend file')
    return path


def catalog(path, kind):
    if kind not in KINDS:
        raise ValueError('Unknown asset library kind')
    with bpy.data.libraries.load(str(path), link=False) as (available, _):
        return sorted(getattr(available, kind))


def inspect(params, workspace):
    path = source(workspace, params['path'])
    before = digest(path)
    kind = params.get('kind', 'collections')
    names = catalog(path, kind)
    offset, limit = params.get('offset', 0), params.get('limit', 100)
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
        raise ValueError('Use a nonnegative offset and limit from 1 to 1000')
    if digest(path) != before:
        raise ValueError('Library changed during inspection')
    return {'path': str(path), 'sha256': before, 'bytes': path.stat().st_size, 'kind': kind,
            'names': names[offset:offset+limit], 'total': len(names), 'offset': offset, 'limit': limit}


def ids():
    return {item for prop in bpy.data.bl_rna.properties if prop.type == 'COLLECTION'
            for item in getattr(bpy.data, prop.identifier) if isinstance(item, bpy.types.ID)}


def image_receipts(images, workspace):
    root = Path(workspace).resolve()
    result = []
    for image in sorted(images, key=lambda i: i.name):
        if image.packed_file:
            files = [{'path': p.filepath, 'bytes': len(p.packed_file.data),
                      'sha256': hashlib.sha256(p.packed_file.data).hexdigest()} for p in image.packed_files]
            result.append({'name': image.name, 'packed': True, 'files': files,
                'bytes': sum(p['bytes'] for p in files), 'sha256': files[0]['sha256'] if len(files) == 1
                else hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()})
        elif image.source == 'GENERATED':
            result.append({'name': image.name, 'packed': False, 'source': image.source})
        else:
            path = Path(bpy.path.abspath(image.filepath, library=image.library)).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise ValueError('Image dependency is missing or outside the workspace: '+image.name)
            result.append({'name': image.name, 'packed': False, 'path': str(path),
                           'bytes': path.stat().st_size, 'sha256': digest(path)})
    return result


def append(params, workspace):
    path = source(workspace, params['path'])
    expected = params.get('expected_sha256')
    if not isinstance(expected, str) or digest(path) != expected:
        raise ValueError('Library SHA-256 does not match; inspect the source again')
    kind = params.get('kind', 'collections')
    available = catalog(path, kind)
    names = params.get('names')
    if (not isinstance(names, list) or not 1 <= len(names) <= 256
            or any(not isinstance(n, str) for n in names) or len(set(names)) != len(names)
            or not set(names) <= set(available)):
        raise ValueError('Choose 1 to 256 unique names present in the inspected library')
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Switch to Object Mode before appending assets')
    before = ids()
    selected, active = list(bpy.context.selected_objects), bpy.context.view_layer.objects.active
    layer, scene, filepath = bpy.context.view_layer.active_layer_collection, bpy.context.scene, bpy.data.filepath
    roots, mappings = {}, []

    def imported(context):
        # Native import events retain source names even when Blender adds suffixes.
        for item in context.import_items:
            if item.id is None or item.source_library is None:
                continue
            library = str(Path(bpy.path.abspath(item.source_library.filepath)).resolve())
            mappings.append({'source_library': library, 'source_name': item.name,
                             'id_type': item.id_type, 'name': item.id.name})
            if library == str(path) and item.id_type == KINDS[kind][1] and item.name in names:
                roots[item.name] = item.id

    bpy.app.handlers.blend_import_post.append(imported)
    try:
        status = bpy.ops.wm.append(directory=str(path)+'/'+KINDS[kind][0]+'/',
            files=[{'name': name} for name in names], link=False, do_reuse_local_id=False,
            clear_asset_data=False, autoselect=False, active_collection=True,
            instance_collections=False, use_recursive=True, set_fake=kind in {'materials', 'node_groups'})
        if status != {'FINISHED'} or set(roots) != set(names):
            raise RuntimeError('Native append did not return every selected source ID')
        created = ids()-before
        if any(value not in created or value.library for value in roots.values()):
            raise RuntimeError('Native append did not create independent local IDs')
        if bpy.context.scene != scene or bpy.data.filepath != filepath:
            raise RuntimeError('Append changed the active project')
        images = image_receipts([v for v in created if isinstance(v, bpy.types.Image)], workspace)
        if digest(path) != expected:
            raise ValueError('Library changed during append')
        counts = {}
        for value in created:
            counts[value.id_type] = counts.get(value.id_type, 0)+1
        return {'path': str(path), 'sha256': expected, 'bytes': path.stat().st_size, 'kind': kind,
                'roots': [{'source_name': name, 'name': roots[name].name,
                           'id_type': roots[name].id_type, 'asset': roots[name].asset_data is not None}
                          for name in names], 'created_counts': counts,
                'items': mappings[:1000], 'items_truncated': len(mappings) > 1000, 'images': images}
    except Exception:
        created = ids()-before
        if created:
            bpy.data.batch_remove(ids=tuple(created))
        raise
    finally:
        bpy.app.handlers.blend_import_post.remove(imported)
        bpy.context.view_layer.active_layer_collection = layer
        for value in list(bpy.context.selected_objects):
            value.select_set(False)
        for value in selected:
            if value.name in bpy.context.view_layer.objects:
                value.select_set(True)
        bpy.context.view_layer.objects.active = active
