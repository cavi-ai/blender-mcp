"""Read-only ray intersections with checked source topology and corner UVs."""
import math
from array import array

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest, page_source
from .blender_uv_charts import uv_digest
from .skin_projection import barycentric_factors
from .surface_ray import local_ray

DEFORMERS = frozenset({'ARMATURE','CAST','CORRECTIVE_SMOOTH','CURVE','DISPLACE','HOOK',
    'LAPLACIANDEFORM','LAPLACIANSMOOTH','LATTICE','MESH_DEFORM','SHRINKWRAP','SIMPLE_DEFORM',
    'SMOOTH','SURFACE_DEFORM','WARP','WAVE'})


def topology(mesh):
    signature = [len(mesh.vertices)]
    for items,attribute,width in ((mesh.edges,'vertices',2), (mesh.polygons,'loop_total',1),
                                  (mesh.loops,'vertex_index',1)):
        values = array('i',[0])*(len(items)*width)
        items.foreach_get(attribute,values)
        signature.append(values.tobytes())
    return tuple(signature)


def cast(mesh, matrix, spec, unit, camera_query):
    origin,direction,distance = local_ray(spec['origin_world'],spec['direction_world'],
        spec['max_distance_m'],matrix,unit)
    mesh.calc_loop_triangles()
    if len(mesh.loop_triangles) > 500000:
        raise ValueError('Surface picking supports at most 500000 triangles')
    report={'hit':False}
    if not mesh.loop_triangles:
        return report
    triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
    coordinates = [tuple(v.co) for v in mesh.vertices]
    tree = BVHTree.FromPolygons(coordinates,triangles,all_triangles=True)
    point,normal,index,_ = tree.ray_cast(Vector(origin),Vector(direction),distance)
    if point is None:
        return report
    world = matrix[:3,:3] @ np.asarray(point,dtype=np.float64)+matrix[:3,3]
    distance_m = math.dist(world,spec['origin_world'])*unit
    if distance_m > spec['max_distance_m']:
        return report
    if camera_query is not None:
        from .blender_camera_ray import inside_clip

        if not inside_clip(world,camera_query):
            return report
    world_normal = np.linalg.inv(matrix[:3,:3]).T @ np.asarray(normal,dtype=np.float64)
    norm = math.hypot(*world_normal)
    if not 0 < norm < math.inf or not np.isfinite(world).all():
        raise ValueError('Surface intersection produced nonfinite world geometry')
    triangle = mesh.loop_triangles[index]
    factors = barycentric_factors(tuple(point),[coordinates[i] for i in triangle.vertices])
    if min(factors) < -1e-5 or max(factors) > 1+1e-5:
        raise ValueError('Surface intersection is outside its source triangle')
    report.update(hit=True,face_index=triangle.polygon_index,
        triangle_vertices=list(triangle.vertices),triangle_loops=list(triangle.loops),
        material_index=mesh.polygons[triangle.polygon_index].material_index,
        position_local=list(point),position_world=world.tolist(),
        normal_world=(world_normal/norm).tolist(),distance_m=distance_m,barycentric=list(factors))
    return report


def uv_position(layer, hit):
    uv=[sum(weight*layer.data[loop].uv[axis]
            for weight,loop in zip(hit['barycentric'],hit['triangle_loops'],strict=True)) for axis in range(2)]
    if not all(math.isfinite(v) for v in uv):
        raise ValueError('Picked source UV coordinates must be finite')
    return uv


def material_binding(value, index):
    slot=value.material_slots[index] if index < len(value.material_slots) else None
    return {'index':index,'name':slot.material.name if slot and slot.material else None,
            'link':slot.link if slot else None}


def inspect(p):
    evaluated = None
    try:
        with preflight():
            value,_,_ = page_source(p)
            source = value.data
            bpy.context.view_layer.update()
            spec = p['surface_ray']
            camera_query=None
            if type(spec.get('evaluated',False)) is not bool:
                raise ValueError('evaluated must be a boolean')
            if 'camera' in spec:
                from .blender_camera_ray import from_query

                spec,camera_query=from_query(spec)
            layer = source.uv_layers.get(p['uv_layer']) if p.get('uv_layer') is not None else None
            if p.get('uv_layer') is not None and layer is None:
                raise ValueError('Requested UV layer is missing')
            mesh = source
            if spec.get('evaluated',False):
                if any(m.show_viewport and m.type not in DEFORMERS for m in value.modifiers):
                    raise ValueError('Evaluated surface picking needs a deform-only stack with source topology mapping')
                graph = bpy.context.evaluated_depsgraph_get()
                evaluated = value.evaluated_get(graph)
                mesh = evaluated.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
                if len(mesh.vertices) > 500000 or len(mesh.loops) > 1500000:
                    raise ValueError('Surface picking exceeds the evaluated geometry budget')
                if topology(mesh) != topology(source):
                    raise ValueError('Evaluated topology differs from the source; source indices are unavailable')
            unit = bpy.context.scene.unit_settings.scale_length
            matrix = np.asarray((evaluated or value).matrix_world,dtype=np.float64)
            report = {**cast(mesh,matrix,spec,unit,camera_query),
                'geometry':'evaluated_current_frame' if evaluated else 'source_mesh',
                'frame':bpy.context.scene.frame_current,'frame_subframe':bpy.context.scene.frame_subframe,
                'scene_unit_meters':unit,'matrix_world':matrix.tolist(),'ray':dict(spec),
                'surface_sha256':mesh_digest(mesh),'intersection_precision':'native_float32_bvh'}
            result = {'name':value.name,'type':'MESH','mesh':source.name,'scope':'mesh_surface_pick',
                'mesh_sha256':mesh_digest(source),'surface_pick':report}
            if camera_query is not None:
                report['camera_query']=camera_query
            if layer is not None:
                report['uv'] = {'layer':layer.name,'sha256':uv_digest(layer)}
            if report['hit']:
                report['material']=material_binding(value,report['material_index'])
                if layer is not None:
                    report['uv']['position']=uv_position(layer,report)
            return result
    finally:
        if evaluated is not None:
            evaluated.to_mesh_clear()
