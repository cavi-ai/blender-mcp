"""Branch a tuned collection instance using native dependency copying."""

from pathlib import Path
from tempfile import TemporaryDirectory

import bpy

from .blender_asset_library import ids, native_append
from .blender_bridge import info
from .blender_collection_instances import members, root


def make_unique(params, workspace):
    value = root(params['name'])
    label = params.get('new_name')
    if (not isinstance(label, str) or not label.strip() or '\0' in label
            or len(label.encode()) > 63 or label in bpy.data.collections):
        raise ValueError('Collection name must be unique, nonempty and at most 63 UTF-8 bytes')
    if bpy.context.mode != 'OBJECT':
        raise ValueError('Switch to Object Mode before making an instance unique')
    if not value.is_editable:
        raise ValueError('Placement needs an editable local object or library override')
    original = value.instance_collection
    original_members = members(original)
    before = ids()
    try:
        # The private native snapshot captures current overrides, not the saved library.
        # Absolute image paths keep existing external texture bindings intact.
        with TemporaryDirectory(prefix='.cavi-variant-', dir=Path(workspace).resolve()) as folder:
            path = Path(folder)/'source.blend'
            bpy.data.libraries.write(str(path), {original}, path_remap='ABSOLUTE', compress=True)
            roots, mappings = native_append(path, 'collections', [original.name], True)
        clone = roots[original.name]
        created = ids()-before
        if clone not in created or clone.library or any(v in original_members or v.library for v in members(clone)):
            raise RuntimeError('Native copy did not produce an independent local definition')
        old_name = clone.name
        clone.name = label
        if clone.name != label:
            raise RuntimeError('Blender changed the requested collection name')
        for item in mappings:
            if item['id_type'] == 'COLLECTION' and item['name'] == old_name:
                item['name'] = clone.name
        # Append creates a staging placement; the existing scene object owns the variant.
        for item in created:
            if (isinstance(item, bpy.types.Object) and item.name in bpy.context.scene.objects
                    and item.instance_type == 'COLLECTION' and item.instance_collection == clone):
                bpy.data.objects.remove(item, do_unlink=True)
        value.instance_collection = clone
        value.update_tag()
        bpy.context.view_layer.update()
        counts = {}
        for item in ids()-before:
            counts[item.id_type] = counts.get(item.id_type, 0)+1
        return {**info(value), 'source_collection': original.name, 'instance_collection': clone.name,
                'created_counts': counts,
                'items': [{k: v for k, v in item.items() if k != 'source_library'} for item in mappings[:1000]],
                'items_truncated': len(mappings) > 1000}
    except Exception:
        if value.instance_collection != original:
            value.instance_collection = original
        created = ids()-before
        if created:
            bpy.data.batch_remove(ids=tuple(created))
        value.update_tag()
        bpy.context.view_layer.update()
        raise
