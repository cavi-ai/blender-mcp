"""Finite affine sampling shared by motion and contact validation."""

import math


def bounded_samples(start, end, samples):
    """Every integer frame when the requested count can hold the range.

    A shorter count stays evenly spaced. The flag is false when a frame in the
    range was not evaluated, so a pass on those samples is not a continuous pass.
    """
    if (type(start) is not int or type(end) is not int or type(samples) is not int
            or isinstance(samples, bool) or not start < end or samples < 2):
        raise ValueError('Sample frames require an increasing integer range and at least two samples')
    if end - start + 1 <= samples:
        return list(range(start, end + 1)), True
    return [start + (end - start) * i / (samples - 1) for i in range(samples)], False


def mapped_frames(frames, scale=1, offset=0):
    if (type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0
            or type(offset) not in (int, float) or not math.isfinite(offset)):
        raise ValueError('Frame mapping needs a finite positive scale and finite offset')
    result = [frame*scale+offset for frame in frames]
    if any(not math.isfinite(frame) for frame in result):
        raise ValueError('Mapped sample times must be finite')
    return result
