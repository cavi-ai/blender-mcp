"""Current full-frame camera projection identities and pixel-center rays."""
import hashlib
import json

import bpy
import numpy as np

from .blender_bridge import obj
from .surface_ray import pixel_ray


def snapshot(camera, image_size):
    scene=bpy.context.scene
    render=scene.render
    actual=[render.resolution_x*render.resolution_percentage//100,
            render.resolution_y*render.resolution_percentage//100]
    if list(image_size) != actual:
        raise ValueError('Declared image size differs from the current render raster')
    if render.use_border or render.use_multiview:
        raise ValueError('Camera pixel queries require a single full-frame render')
    graph=bpy.context.evaluated_depsgraph_get()
    camera=camera.evaluated_get(graph)
    if camera.type != 'CAMERA' or camera.data.type not in ('PERSP','ORTHO'):
        raise ValueError('Camera pixel queries require a perspective or orthographic camera')
    matrix=camera.calc_matrix_camera(graph,x=actual[0],y=actual[1],
        scale_x=render.pixel_aspect_x,scale_y=render.pixel_aspect_y)
    result={'camera':camera.name,'type':camera.data.type,'image_size':actual,
        'pixel_aspect':[render.pixel_aspect_x,render.pixel_aspect_y],
        'matrix_world':[list(row) for row in camera.matrix_world.normalized()],
        'projection':[list(row) for row in matrix],
        'clip_start':camera.data.clip_start,'clip_end':camera.data.clip_end,
        'frame':scene.frame_current,'subframe':scene.frame_subframe,
        'depth_of_field':camera.data.dof.use_dof}
    pixel_ray([0,0],actual,result['projection'],result['matrix_world'],result['type'],
              result['clip_start'],result['clip_end'])
    result['sha256']=hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    result['available']=True
    return result


def from_query(query):
    view=snapshot(obj(query['camera']),query['image_size'])
    expected=query.get('expected_projection_sha256')
    if expected is not None and expected != view['sha256']:
        raise ValueError('Camera projection changed; capture or inspect the current view')
    origin,direction,span=pixel_ray(query['pixel'],view['image_size'],view['projection'],
        view['matrix_world'],view['type'],view['clip_start'],view['clip_end'])
    unit=bpy.context.scene.unit_settings.scale_length
    ray={'origin_world':origin,'direction_world':direction,
        'max_distance_m':min(query['max_distance_m'],span*unit),'evaluated':query.get('evaluated',False)}
    return ray,{'query':dict(query),'projection':view,'identity_checked':expected is not None}


def inside_clip(point, context):
    view=context['projection']
    camera=np.linalg.solve(np.asarray(view['matrix_world'],dtype=np.float64),[*point,1.])
    return view['clip_start'] <= -camera[2] <= view['clip_end']
