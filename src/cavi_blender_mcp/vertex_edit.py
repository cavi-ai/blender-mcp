"""Plan translations using the coordinate storage of the native mesh."""
import math
from array import array


def translated(rows, offset):
    result = []
    try:
        for point in rows:
            if (len(point) != 3 or len(offset) != 3
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*point,*offset))):
                raise ValueError('Vertex coordinates and offset must be finite 3D vectors')
            target = tuple(array('f', (a+b for a,b in zip(point,offset,strict=True))))
            if not all(math.isfinite(v) for v in target):
                raise ValueError('Translated coordinates exceed native float storage')
            result.append(target)
    except OverflowError as exc:
        raise ValueError('Translated coordinates exceed native float storage') from exc
    return result
