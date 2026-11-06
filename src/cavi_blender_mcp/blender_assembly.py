"""Export current evaluated collection-instance mesh surfaces without editing source data."""

import shutil
from contextlib import contextmanager, nullcontext

import bpy
from mathutils import Matrix

from .blender_bridge import obj, output_file
from .blender_export import prepared_images, preset_for, sidecars, texture_receipt, write
from .blender_geometry import triangle_count


@contextmanager
def evaluated_meshes(names):
    if not isinstance(names, list) or not 1 <= len(names) <= 1000 or len(set(names)) != len(names):
        raise ValueError('Select 1 to 1000 unique collection-instance objects')
    roots = {obj(name) for name in names}
    if any(r.type != 'EMPTY' or r.instance_type != 'COLLECTION' or not r.instance_collection for r in roots):
        raise ValueError('Assembly roots must be collection-instance empties')
    if any(r.hide_get() or r.hide_viewport for r in roots):
        raise ValueError('Requested assembly root is hidden')
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    samples, omitted, empty = [], {}, []
    for instance in depsgraph.object_instances:
        if not instance.is_instance or not instance.show_self or instance.parent is None or instance.parent.original not in roots:
            continue
        value = instance.object
        if value.type != 'MESH':
            omitted[value.type] = omitted.get(value.type, 0)+1
        elif not value.data.polygons:
            empty.append(value.original.name)
        else:
            samples.append((instance.parent.original.name, value.original, instance.matrix_world.copy()))
    if not samples:
        raise ValueError('Selected assemblies contain no evaluated mesh surfaces')
    samples.sort(key=lambda s: (s[0], s[1].original.name, tuple(v for row in s[2] for v in row)))
    meshes, objects, placements, prepared = {}, [], [], []
    try:
        for root, original, matrix in samples:
            value = original.evaluated_get(depsgraph)
            transform = Matrix.LocRotScale(*matrix.decompose())
            residual = transform.inverted_safe() @ matrix
            axes = [matrix.to_3x3().col[i].normalized() for i in range(3)]
            sheared = any(abs(axes[i].dot(axes[j])) > 1e-6 for i in range(3) for j in range(i))
            materials = tuple(slot.material for slot in value.material_slots)
            key = (value.data.as_pointer(), tuple(m.as_pointer() if m else 0 for m in materials),
                   tuple(v for row in residual for v in row) if sheared else ())
            if key not in meshes:
                mesh = bpy.data.meshes.new_from_object(value, preserve_all_data_layers=True, depsgraph=depsgraph)
                meshes[key] = mesh
                # Evaluated meshes can gain materials from Geometry Nodes even when
                # the source object has no material slots. Preserve those slots.
                for index, slot in enumerate(value.material_slots):
                    if slot.link == 'OBJECT' and index < len(mesh.materials):
                        mesh.materials[index] = slot.material
                if sheared:
                    mesh.transform(residual)
            prepared.append((root, original.name, meshes[key], matrix, transform, sheared))
        # Finish reading evaluated data before linking temporary objects into the scene.
        for root, source_name, mesh, matrix, transform, sheared in prepared:
            copy = bpy.data.objects.new(f'{root}_{source_name}_{len(objects):03d}', mesh)
            objects.append(copy)
            bpy.context.scene.collection.objects.link(copy)
            copy.matrix_world = transform
            placements.append({'root': root, 'source_object': source_name,
                'exported_name': copy.name, 'matrix_world': [list(row) for row in matrix],
                'triangles': triangle_count(mesh), 'shear_baked': sheared})
        bpy.context.view_layer.update()
        yield objects, {'placements': placements, 'unique_meshes': len(meshes),
                        'triangles': sum(p['triangles'] for p in placements),
                        'non_mesh_instance_counts': omitted, 'empty_mesh_instances': sorted(set(empty))}
    finally:
        for value in objects:
            bpy.data.objects.remove(value, do_unlink=True)
        for mesh in meshes.values():
            bpy.data.meshes.remove(mesh)
        bpy.context.view_layer.update()


def export(params):
    path_text = params['path']
    suffix = '.'+path_text.rsplit('.', 1)[-1].lower()
    if suffix not in {'.glb', '.fbx'}:
        raise ValueError('Static assembly export supports FBX or GLB')
    preset = preset_for(params, suffix)
    textures = params.get('textures', False)
    if type(textures) is not bool:
        raise ValueError('textures must be boolean')
    if textures and suffix != '.fbx':
        raise ValueError('Texture sidecars apply to FBX; GLB embeds its supported images')
    triangulate = params.get('triangulate', False)
    if type(triangulate) is not bool or (triangulate and suffix != '.fbx'):
        raise ValueError('triangulate must be boolean and applies only to FBX exports')
    with output_file(path_text, {'.glb', '.fbx'}) as path, evaluated_meshes(params['names']) as (objects, report):
        directory = sidecars(path) if textures else None
        try:
            with prepared_images(objects, directory) if textures else nullcontext():
                uv_result=write(path, objects, objects, preset, False, False, textures=textures,
                                uv_layer=params.get('uv_layer'), triangulate=triangulate)
            files = texture_receipt(directory) if directory else []
        except Exception:
            if directory:
                shutil.rmtree(directory, ignore_errors=True)
            raise
        return {**report,**uv_result, 'path': str(path), 'bytes': path.stat().st_size,
                'roots': params['names'], 'textures': files,
                'scope': 'evaluated_static_assembly_current_frame',
                'frame': bpy.context.scene.frame_current+bpy.context.scene.frame_subframe}
