"""Height fields for terrain: value noise and a full-window image prefilter."""

import numpy as np


def smoothstep(value):
    return value * value * (3 - 2 * value)


def sample(grid, resolution, ease=smoothstep):
    height, width = grid.shape
    x = np.linspace(0, width - 1, resolution)
    y = np.linspace(0, height - 1, resolution)
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    tx = ease(x - x0)
    ty = ease(y - y0)
    top = grid[np.ix_(y0, x0)] * (1 - tx) + grid[np.ix_(y0, x1)] * tx
    bottom = grid[np.ix_(y1, x0)] * (1 - tx) + grid[np.ix_(y1, x1)] * tx
    return top * (1 - ty)[:, None] + bottom * ty[:, None]


def prefilter(grid, resolution):
    """Box-filter each axis with a full window so the border cannot alias.

    Reflection supplies the samples a truncated window would drop. The window
    width is one output spacing, matching the previous interior filter.
    """
    grid = np.asarray(grid, dtype=np.float64)
    if grid.ndim != 2 or min(grid.shape) < 1:
        raise ValueError('Height grids must be non-empty two-dimensional arrays')
    if type(resolution) is not int or resolution < 2:
        raise ValueError('Terrain resolution must be an integer of at least 2')
    for axis in (0, 1):
        count = grid.shape[axis]
        half = (count - 1) // (resolution - 1) // 2
        if half <= 0:
            continue
        pad = [(0, 0), (0, 0)]
        pad[axis] = (half, half)
        padded = np.pad(grid, pad, mode='reflect')
        total = np.insert(np.cumsum(padded, axis=axis), 0, 0.0, axis=axis)
        index = np.arange(count)
        low, high = index, index + 2 * half + 1
        shape = [1, 1]
        shape[axis] = count
        grid = (np.take(total, high, axis=axis) - np.take(total, low, axis=axis)) / (2 * half + 1)
    return grid


def noise(resolution, seed, octaves, frequency):
    """Octave value noise in its native 0–1 range, without per-seed stretching."""
    rng = np.random.default_rng(seed)
    total = np.zeros((resolution, resolution), np.float64)
    amplitude, weight = 1.0, 0.0
    for octave in range(octaves):
        cells = min(max(2, round(frequency * 2 ** octave)), max(2, resolution - 1))
        lattice = rng.random((cells + 1, cells + 1))
        total += amplitude * sample(lattice, resolution)
        weight += amplitude
        amplitude *= 0.5
    total /= weight
    if not np.isfinite(total).all():
        raise ValueError('Terrain noise must be finite')
    if float(total.max() - total.min()) < 1e-9:
        return np.zeros_like(total)
    return total
