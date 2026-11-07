"""Nearest evaluated mesh discovery in the current view layer, including instances."""
import math

import bpy
import numpy as np

from .blender_camera_ray import from_query
from .blender_errors import preflight
from .blender_mesh_regions import mesh_digest
from .blender_surface_pick import DEFORMERS, cast, material_binding, topology, uv_position
from .blender_uv_charts import uv_digest
from .surface_ray import bounds_intersect


def inspect(p):
    with preflight():
        if bpy.context.mode!='OBJECT':
            raise ValueError('Inspect scene surfaces in Object Mode')
        if not p['surface_ray'].get('evaluated'):
            raise ValueError('Scene camera picking requires evaluated=true')
        bpy.context.view_layer.update()
        ray,camera=from_query(p['surface_ray'])
        graph=bpy.context.evaluated_depsgraph_get()
        unit=bpy.context.scene.unit_settings.scale_length
        if not math.isfinite(unit) or unit<=0:
            raise ValueError('Scene unit scale must be positive and finite')
        result={'scope':'scene_surface_pick','surface_pick':{'hit':False}}
        best=None
        triangles=vertices=0
        for instance in graph.object_instances:
            value=instance.object
            parent=instance.parent
            if (value.type!='MESH' or value.original.type!='MESH' or not instance.show_self
                    or value.hide_render or not value.visible_camera
                    or (parent is not None and (parent.hide_render or not parent.visible_camera))):
                continue
            matrix=np.asarray(instance.matrix_world,dtype=np.float64)
            if not value.data.polygons:
                continue
            corners=np.asarray(value.bound_box,dtype=np.float64)@matrix[:3,:3].T+matrix[:3,3]
            if not bounds_intersect(ray['origin_world'],ray['direction_world'],ray['max_distance_m']/unit,corners):
                continue
            identity={'is_instance':instance.is_instance,'parent':parent.original.name if parent else None,
                      'persistent_id':list(instance.persistent_id),'matrix_world':matrix.tolist()}
            mesh=value.to_mesh(preserve_all_data_layers=True,depsgraph=graph)
            try:
                vertices+=len(mesh.vertices)
                triangles+=sum(max(0,len(f.vertices)-2) for f in mesh.polygons)
                if vertices>500000 or triangles>500000:
                    raise ValueError('Scene picking exceeds 500000 evaluated vertices or triangles')
                hit=cast(mesh,matrix,ray,unit,camera)
                if not hit['hit'] or (best is not None and hit['distance_m']>=best):
                    continue
                source=value.original.data
                mapped=(not any(m.show_viewport and m.type not in DEFORMERS for m in value.original.modifiers)
                        and topology(mesh)==topology(source))
                hit.update(matrix_world=matrix.tolist(),surface_sha256=mesh_digest(mesh),instance=identity,
                    material=material_binding(value,hit['material_index']),
                    source_mapping={'available':mapped,'reason':None if mapped else 'Evaluated geometry has no checked source topology mapping'})
                if mapped:
                    layer=source.uv_layers.get(p['uv_layer']) if p.get('uv_layer') is not None else None
                    if layer is not None:
                        hit['uv']={'layer':layer.name,'sha256':uv_digest(layer),'position':uv_position(layer,hit)}
                    elif p.get('uv_layer') is not None:
                        hit['uv']={'available':False,'reason':'Requested source UV layer is missing'}
                else:
                    for field in ('face_index','triangle_vertices','triangle_loops'):
                        hit['evaluated_'+field]=hit.pop(field)
                best=hit['distance_m']
                result={'name':value.original.name,'type':'MESH','mesh':source.name,
                    'mesh_sha256':mesh_digest(source),'scope':'scene_surface_pick','surface_pick':hit}
            finally:
                value.to_mesh_clear()
        result['surface_pick'].update(camera_query=camera,ray=ray,
            geometry='evaluated_view_layer_meshes',frame=bpy.context.scene.frame_current,
            frame_subframe=bpy.context.scene.frame_subframe,scene_unit_meters=unit,
            view_layer=bpy.context.view_layer.name,intersection_precision='native_float32_bvh',
            geometry_considered={'vertices':vertices,'triangles':triangles},
            not_checked=['shader_opacity','non_mesh_geometry','render_only_visibility','render_modifier_differences'])
        return result
