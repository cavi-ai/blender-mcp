"""Selected-surface density policy and measurements in physical texture pixels."""
import math

from .mapping import measure_triangle, summarize
from .uv_regions import quality, region


def options(target, destination, scale):
    if target is None and destination is None:
        return None
    if target is None or destination is None:
        raise ValueError('Density matching requires target_px_per_m and uv_region together')
    if type(target) not in (int, float) or not math.isfinite(target) or not 0 < target <= 100000:
        raise ValueError('target_px_per_m must be finite, positive and at most 100000')
    if tuple(scale) != (1, 1):
        raise ValueError('Density matching computes a uniform scale; omit the explicit scale')
    return region(destination)


def measure(geometry, rows, resolution):
    samples = [measure_triangle([geometry['vertices'][i] for i in vertices],
        [rows[i] for i in triangle], resolution) for triangle, vertices in
        zip(geometry['triangles'], geometry['triangle_vertices'], strict=True)]
    report = summarize(samples)
    if (not samples or report['world_degenerate_triangles'] or report['uv_degenerate_triangles']
            or report['uv_missing_triangles'] or report['density_area_weighted'] is None):
        raise ValueError('Density matching requires nondegenerate mapped source triangles')
    return report


def review(geometry, rows, destination, target):
    rows, checked = quality(rows, geometry['triangles'], geometry['triangle_vertices'], destination)
    if not checked['passed']:
        raise ValueError('Requested density does not fit the region, overlap and pixel-gutter checks')
    measured = measure(geometry, rows, destination['texture_resolution'])
    error = abs(measured['density_area_weighted']/target-1)
    if error > 1e-4:
        raise ValueError('Stored UV precision cannot achieve the requested density within 0.01 percent')
    return rows, {'after': measured, 'quality': checked, 'relative_error': error,
                  'relative_tolerance': 1e-4}
