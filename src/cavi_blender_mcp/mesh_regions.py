"""Face-selection validation shared by the MCP and native bridge."""
import math
import re


def selection(faces, offset, face_count=None, expected=None, observed=None):
    if (not isinstance(faces, list) or not 1 <= len(faces) <= 20000
            or any(type(i) is not int or i < 0 or (face_count is not None and i >= face_count) for i in faces)
            or len(set(faces)) != len(faces)):
        raise ValueError('face_indices must contain 1 to 20000 unique current polygon indices')
    if (not isinstance(offset, (list, tuple)) or len(offset) != 3
            or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 1e6 for v in offset)
            or not any(offset)):
        raise ValueError('offset must be a nonzero finite local-space vector')
    if expected is not None:
        if not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected):
            raise ValueError('expected_mesh_sha256 must be a lowercase SHA-256')
        if observed is not None and expected != observed:
            raise ValueError('Mesh geometry changed since inspection; inspect the faces again')
    return faces, [float(v) for v in offset]
