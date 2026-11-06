"""Explicit UV destinations and pixel-space layout checks."""
import math


def projection(method, angle):
    method = 'smart' if method is None else method
    if method not in ('smart', 'angle_based', 'conformal', 'minimum_stretch'):
        raise ValueError('Unknown unwrap_method')
    if method != 'smart':
        if angle is not None:
            raise ValueError('angle_limit_degrees applies only to smart projection')
        return method, None
    angle = 66 if angle is None else angle
    if type(angle) not in (int, float) or not math.isfinite(angle) or not 1 <= angle <= 89:
        raise ValueError('angle_limit_degrees must be finite from 1 to 89')
    return method, angle


def region(value):
    if not isinstance(value, dict) or set(value) - {'bounds', 'texture_resolution', 'margin_px', 'allow_overlap', 'allow_pinned'}:
        raise ValueError('Expected UV region bounds, texture_resolution and margin_px')
    bounds, resolution, padding = (value.get(k) for k in ('bounds', 'texture_resolution', 'margin_px'))
    if (not isinstance(bounds, (tuple, list)) or len(bounds) != 4
            or any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > 1e6 for n in bounds)
            or bounds[2] <= bounds[0] or bounds[3] <= bounds[1]):
        raise ValueError('UV bounds must be finite [min_u,min_v,max_u,max_v] with positive size')
    if (not isinstance(resolution, (tuple, list)) or len(resolution) != 2
            or any(type(n) is not int or not 1 <= n <= 16384 for n in resolution)):
        raise ValueError('texture_resolution requires two integers from 1 to 16384')
    if type(padding) not in (int, float) or not math.isfinite(padding) or not 0 <= padding <= 256:
        raise ValueError('margin_px must be finite from 0 to 256')
    if min((bounds[2]-bounds[0])*resolution[0], (bounds[3]-bounds[1])*resolution[1]) <= 2*padding:
        raise ValueError('UV region is too small for the requested pixel padding')
    flags = {k: value.get(k, False) for k in ('allow_overlap', 'allow_pinned')}
    if any(type(v) is not bool for v in flags.values()):
        raise ValueError('UV region flags must be boolean')
    return {'bounds': list(bounds), 'texture_resolution': list(resolution), 'margin_px': float(padding), **flags}


def frame(spec):
    lo_u, lo_v, hi_u, hi_v = spec['bounds']
    width, height = spec['texture_resolution']
    padding = spec['margin_px']
    available = min((hi_u-lo_u)*width, (hi_v-lo_v)*height)-2*padding
    # Reserve subpixel headroom for Blender's float UV storage; never relax the requested gutter.
    border = padding + min(.5, available*.1)
    scale = min((hi_u-lo_u)*width, (hi_v-lo_v)*height)-2*border
    origin = ((lo_u+hi_u)/2-scale/(2*width), (lo_v+hi_v)/2-scale/(2*height))
    return origin, scale


def map_uv(rows, spec):
    origin, scale = frame(spec)
    width, height = spec['texture_resolution']
    if any(len(row) != 2 or any(not math.isfinite(v) or not -1e-6 <= v <= 1+1e-6 for v in row) for row in rows):
        raise ValueError('Native packed UVs must fit the unit square')
    return [(origin[0]+min(1., max(0., u))*scale/width,
             origin[1]+min(1., max(0., v))*scale/height) for u,v in rows]


def reservation(triangles, spec):
    if spec['allow_overlap']:
        return {'checked': False}
    import numpy as np

    from .uv_layout import AREA_EPSILON, triangle_intersection_area

    u0,v0,u1,v1 = spec['bounds']
    resolution = np.asarray(spec['texture_resolution'])
    box = np.asarray([(u0,v0),(u1,v0),(u1,v1),(u0,v1)])*resolution
    checked = 0
    for row in triangles:
        tri = np.asarray(row, dtype=float)
        if tri.shape != (3,2) or not np.isfinite(tri).all():
            raise ValueError('Unselected UVs must be finite before reserving a region')
        checked += 1
        if (tri[:,0].max() <= u0 or tri[:,0].min() >= u1
                or tri[:,1].max() <= v0 or tri[:,1].min() >= v1):
            continue
        pixels = tri*resolution
        if sum(triangle_intersection_area(pixels, box[ids]) for ids in ([0,1,2],[0,2,3])) > AREA_EPSILON:
            raise ValueError('UV region is occupied by unselected faces; choose clear bounds or allow_overlap explicitly')
    return {'checked': True, 'unselected_triangles': checked}


def quality(rows, triangles, vertices, spec):
    import numpy as np

    from .uv_layout import DISTANCE_EPSILON, analyze

    uv = np.asarray(rows, dtype=np.float32).astype(np.float64)
    report = analyze(uv[np.asarray(triangles)], vertices, spec['texture_resolution'], spec['margin_px'])
    u0,v0,u1,v1 = spec['bounds']
    width,height = spec['texture_resolution']
    border = float(min(((uv[:,0]-u0)*width).min(), ((u1-uv[:,0])*width).min(),
                       ((uv[:,1]-v0)*height).min(), ((v1-uv[:,1])*height).min()))
    passed = (report['complete'] and not report['nonfinite_triangles'] and not report['degenerate_triangles']
              and not report['overlap']['triangle_pairs'] and not report['padding']['triangle_pairs_below_requested']
              and border+DISTANCE_EPSILON >= spec['margin_px'])
    return uv.tolist(), {'passed': bool(passed), 'complete': report['complete'], 'charts': report['charts'],
        'triangles': report['triangles'], 'overlap_pairs': report['overlap']['triangle_pairs'],
        'degenerate_triangles': report['degenerate_triangles'],
        'padding_pairs_below_requested': report['padding']['triangle_pairs_below_requested'],
        'minimum_region_border_pixels': border, 'requested_padding_pixels': spec['margin_px']}
