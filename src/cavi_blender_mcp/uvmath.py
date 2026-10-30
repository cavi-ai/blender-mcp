"""Vectorized UV measurements; numpy only, no application dependency."""

import numpy as np

CHUNK = 1 << 21


def _inside(tri, sign, px, py):
    a, b, c = tri[:, 0:1], tri[:, 1:2], tri[:, 2:3]
    inside = None
    for p, q in ((a, b), (b, c), (c, a)):
        edge = ((q[..., 0] - p[..., 0]) * (py - p[..., 1])
                - (q[..., 1] - p[..., 1]) * (px - p[..., 0])) * sign
        # Strict: shared edges of adjacent triangles never count twice.
        inside = edge > 1e-9 if inside is None else inside & (edge > 1e-9)
    return inside


def coverage(triangles, resolution):
    """Per-cell triangle counts of UV triangles (n, 3, 2) rasterized at cell centers."""
    if type(resolution) is not int or not 1 <= resolution <= 4096:
        raise ValueError("Raster resolution must be an integer from 1 to 4096")
    counts = np.zeros(resolution * resolution, np.int32)
    tri = np.asarray(triangles, np.float64).reshape(-1, 3, 2) * resolution
    if not len(tri):
        return counts.reshape(resolution, resolution)
    if not np.isfinite(tri).all():
        raise ValueError("UV coordinates must be finite")
    area = ((tri[:, 1, 0] - tri[:, 0, 0]) * (tri[:, 2, 1] - tri[:, 0, 1])
            - (tri[:, 1, 1] - tri[:, 0, 1]) * (tri[:, 2, 0] - tri[:, 0, 0]))
    lo = np.clip(np.ceil(tri.min(axis=1) - 0.5), 0, resolution).astype(np.int64)
    hi = np.clip(np.floor(tri.max(axis=1) - 0.5), -1, resolution - 1).astype(np.int64)
    size = hi - lo + 1
    keep = (np.abs(area) > 1e-12) & (size > 0).all(axis=1)
    tri, area, lo, size = tri[keep], area[keep], lo[keep], size[keep]
    sign = np.sign(area)[:, None]
    span = size.max(axis=1)
    bucket = np.ceil(np.log2(np.maximum(span, 1))).astype(np.int64)
    for level in np.unique(bucket):
        k = 1 << int(level)
        members = np.nonzero(bucket == level)[0]
        ox, oy = (grid.ravel() for grid in np.meshgrid(np.arange(k), np.arange(k)))
        step = max(1, CHUNK // (k * k))
        if k * k <= CHUNK:
            for start in range(0, len(members), step):
                rows = members[start:start + step]
                px = lo[rows, 0:1] + ox[None]
                py = lo[rows, 1:2] + oy[None]
                mask = (ox[None] < size[rows, 0:1]) & (oy[None] < size[rows, 1:2])
                mask &= _inside(tri[rows], sign[rows], px + 0.5, py + 0.5)
                counts += np.bincount((py * resolution + px)[mask], minlength=counts.size
                                      ).astype(np.int32)
            continue
        for row in members:
            width, height = size[row]
            band = max(1, CHUNK // width)
            xs = np.arange(width)
            for top in range(0, height, band):
                gx, gy = np.meshgrid(xs, np.arange(top, min(height, top + band)))
                px = (lo[row, 0] + gx.ravel())[None]
                py = (lo[row, 1] + gy.ravel())[None]
                mask = _inside(tri[row:row + 1], sign[row:row + 1], px + 0.5, py + 0.5)
                counts += np.bincount((py * resolution + px)[mask], minlength=counts.size
                                      ).astype(np.int32)
    return counts.reshape(resolution, resolution)


def overlap(triangles, resolution):
    counts = coverage(triangles, resolution)
    covered = int((counts > 0).sum())
    overlapped = int((counts > 1).sum())
    return {"raster_resolution": resolution, "covered_cells": covered,
            "overlapping_cells": overlapped, "coverage_ratio": covered / counts.size,
            "overlap_ratio": overlapped / covered if covered else 0.0}


def density(points, uvs, resolution):
    """Area-weighted px/m over triangles (n, 3, 3) metres and (n, 3, 2) UVs."""
    points = np.asarray(points, np.float64).reshape(-1, 3, 3)
    uvs = np.asarray(uvs, np.float64).reshape(-1, 3, 2)
    world = np.linalg.norm(np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]),
                           axis=1) / 2
    d1, d2 = uvs[:, 1] - uvs[:, 0], uvs[:, 2] - uvs[:, 0]
    uv = np.abs(d1[:, 0] * d2[:, 1] - d1[:, 1] * d2[:, 0]) / 2
    valid = (world > 1e-12) & (uv > 1e-12)
    mapped = float(world[valid].sum())
    if not mapped:
        return None
    return float(np.sqrt(resolution[0] * resolution[1] * uv[valid].sum() / mapped))
