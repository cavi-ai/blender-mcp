"""Validation for optional exact clearance sample frames."""

import itertools
import math


def validate_sample_frames(frames, start, end):
    """Return finite, increasing explicit frames inside the declared interval."""
    if not isinstance(frames, list) or not 1 <= len(frames) <= 32:
        raise ValueError('sample_frames must contain 1..32 frames')
    if any(type(value) not in (int, float) or not start <= value <= end or not math.isfinite(value)
           for value in frames):
        raise ValueError('sample_frames must be finite numbers within the declared interval')
    if any(left >= right for left, right in itertools.pairwise(frames)):
        raise ValueError('sample_frames must be strictly increasing')
    return [float(value) for value in frames]
