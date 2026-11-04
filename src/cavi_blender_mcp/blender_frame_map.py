"""Finite affine sampling shared by motion and contact validation."""

import math


def mapped_frames(frames, scale=1, offset=0):
    if (type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0
            or type(offset) not in (int, float) or not math.isfinite(offset)):
        raise ValueError('Frame mapping needs a finite positive scale and finite offset')
    result = [frame*scale+offset for frame in frames]
    if any(not math.isfinite(frame) for frame in result):
        raise ValueError('Mapped sample times must be finite')
    return result
