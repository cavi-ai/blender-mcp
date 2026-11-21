"""Asset operation selection for asset_io. This module must not import bpy."""

from pathlib import Path
from typing import NamedTuple

TRIANGULATE_MESSAGE = 'triangulate applies only to FBX exports'


class AssetRoute(NamedTuple):
    kind: str
    operation: str
    params: dict
    args: tuple


def refuse_triangulate(enabled, suffix):
    """Raise the shared refusal. Callers decide what `enabled` means."""
    if enabled and suffix != '.fbx':
        raise ValueError(TRIANGULATE_MESSAGE)


def route_asset(action, path, values, *, lease_id, pick):
    """Select the asset_io branch. Export triangulate is refused before the others."""
    if action == 'export' and values['triangulate'] is not None:
        refuse_triangulate(True, Path(path).suffix.lower())
    if action == 'open':
        params = pick(action, values, (), {'expected_sha256': None})
        return AssetRoute('call', 'open_project', {'lease_id': lease_id, 'path': path, **params}, ())
    if action == 'export' and values['assembly'] is True:
        values.pop('assembly')
        params = pick(action, values, ['names'], {'axis': None, 'textures': False, 'uv_layer': None,
                                                  'triangulate': False})
        if params['uv_layer'] is None:
            params.pop('uv_layer')
        if not params['triangulate']:
            params.pop('triangulate')
        operation = 'export_uv_assembly' if values['uv_layer'] is not None else 'export_assembly'
        return AssetRoute('call', operation, {'path': path, 'lease_id': lease_id, **params}, ())
    if action == 'export' and values['assembly'] is False:
        values.pop('assembly')
    if action == 'generate' and values['prompt'] is not None:
        params = pick(action, values, ['prompt'], {'quality': None})
        return AssetRoute('panorama', 'panorama', {}, (params['prompt'], path, params['quality']))
    if action == 'generate':
        params = pick(action, values, ['image'], {'resolution': None, 'quality': None, 'views': None,
                                                  'guide': None})
        return AssetRoute('generate', 'generate', {}, (
            params['image'], path, params['resolution'], params['quality'], params['views'],
            params['guide']))
    if action == 'import':
        suffix = Path(path).suffix.lower()
        operation = {'.fbx': 'import_fbx', '.obj': 'import_obj',
                     '.usd': 'import_usd', '.usda': 'import_usd',
                     '.usdc': 'import_usd', '.stl': 'import_stl', '.ply': 'import_ply',
                     '.abc': 'import_abc', '.vdb': 'import_vdb'}.get(suffix, 'import_mesh')
        if values['expected_sha256'] is not None and suffix != '.glb':
            raise ValueError('expected_sha256 applies only to GLB imports')
        params = pick(action, values, ['name'], {'expected_sha256': None})
        if params['expected_sha256'] is None:
            params.pop('expected_sha256')
        return AssetRoute('call', operation, {'lease_id': lease_id, 'path': path, **params}, ())
    if action == 'save':
        pick(action, values)
        return AssetRoute('call', 'save_project', {'lease_id': lease_id, 'path': path}, ())
    if values['bake_pair'] is not None:
        params = pick(action, values, ['bake_pair'], {'axis': None})
        params['bake_pair'] = values['bake_pair'].model_dump()
        return AssetRoute('call', 'export_asset', {'lease_id': lease_id, 'path': path, **params}, ())
    params = pick(action, values, ['names'], {
        'preserve_instances': False, 'include_empties': False, 'lods': False, 'collision': False,
        'animations': False, 'textures': False, 'axis': None, 'baked_animation': False,
        'animation_sample_step': None, 'uv_layer': None, 'triangulate': False, 'deform_only': False})
    if not params['deform_only']:
        params.pop('deform_only')
    if params['uv_layer'] is None:
        params.pop('uv_layer')
    else:
        return AssetRoute('call', 'export_uv_asset',
                          {'lease_id': lease_id, 'path': path, **params}, ())
    if (params['lods'] or params['collision'] or params['animations']
            or params['textures'] or params['axis'] or params['baked_animation'] or params['triangulate']
            or params['animation_sample_step'] is not None
            or 'deform_only' in params or path.lower().endswith(('.usd', '.usda', '.usdc'))):
        return AssetRoute('call', 'export_asset', {'lease_id': lease_id, 'path': path, **params}, ())
    for key in ('lods', 'collision', 'animations', 'textures', 'axis', 'baked_animation',
                'animation_sample_step', 'triangulate'):
        params.pop(key)
    # A distinct bridge operation makes older bridges fail before writing a file.
    operation = 'export_instances' if params['preserve_instances'] else 'export_mesh'
    return AssetRoute('call', operation, {'lease_id': lease_id, 'path': path, **params}, ())
