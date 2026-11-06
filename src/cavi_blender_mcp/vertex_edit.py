"""Plan translations using the coordinate storage of the native mesh."""
import math
from array import array
from heapq import heapify, heappop, heappush

from .mesh_regions import indices


def radius_m(value):
    if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
        raise ValueError('Proportional radius must be finite and positive in metres')
    return float(value)


def geodesic_weights(vertices, edges, seeds, radius, *, linear=((1,0,0),(0,1,0),(0,0,1)),
                     unit_m=1., max_affected=20000):
    """Shortest source-edge paths with smoothstep falloff in world metres."""
    radius = radius_m(radius)
    if (not 1 <= len(vertices) <= 500000 or type(max_affected) is not int
            or not 1 <= max_affected <= 20000):
        raise ValueError('Proportional editing supports 500000 source vertices and 20000 affected vertices')
    indices(seeds,len(vertices),'vertex_indices')
    if (len(linear) != 3 or any(len(row) != 3 for row in linear)
            or any(type(v) not in (int,float) or not math.isfinite(v) for row in linear for v in row)
            or type(unit_m) not in (int,float) or not math.isfinite(unit_m) or unit_m <= 0
            or any(len(p) != 3 or any(not math.isfinite(v) for v in p) for p in vertices)):
        raise ValueError('Proportional editing requires finite source coordinates and world metric')
    neighbors = [[] for _ in vertices]
    for count,edge in enumerate(edges,1):
        if (count > 1500000 or len(edge) != 2
                or any(type(i) is not int or not 0 <= i < len(vertices) for i in edge)):
            raise ValueError('Proportional editing supports 1500000 valid source edges')
        a,b = edge
        delta = [vertices[b][i]-vertices[a][i] for i in range(3)]
        length = math.hypot(*(sum(row[i]*delta[i] for i in range(3))*unit_m for row in linear))
        if not math.isfinite(length):
            raise ValueError('Source world-edge lengths must be finite')
        neighbors[a].append((b,length))
        neighbors[b].append((a,length))
    best = dict.fromkeys(seeds,0.)
    pending, result = [(0.,i) for i in seeds], []
    heapify(pending)
    while pending:
        distance,index = heappop(pending)
        if distance != best[index]:
            continue
        t = distance/radius
        weight = (1-t)**2*(1+2*t)
        if weight > 0:
            result.append((index,weight))
            if len(result) > max_affected:
                raise ValueError('Proportional edit exceeds the affected-vertex budget; reduce the radius')
        for neighbor,length in neighbors[index]:
            candidate = distance+length
            if candidate < radius and candidate < best.get(neighbor,math.inf):
                best[neighbor] = candidate
                heappush(pending,(candidate,neighbor))
    return sorted(result)


def translated(rows, offset, weights=None):
    result = []
    weights = [1.]*len(rows) if weights is None else weights
    if (len(weights) != len(rows)
            or any(type(w) not in (int,float) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights)):
        raise ValueError('Vertex weights must match the selected points and lie within 0..1')
    try:
        for point,weight in zip(rows,weights,strict=True):
            if (len(point) != 3 or len(offset) != 3
                    or any(type(v) not in (int,float) or not math.isfinite(v) for v in (*point,*offset))):
                raise ValueError('Vertex coordinates and offset must be finite 3D vectors')
            target = tuple(array('f', (a+b*weight for a,b in zip(point,offset,strict=True))))
            if not all(math.isfinite(v) for v in target):
                raise ValueError('Translated coordinates exceed native float storage')
            result.append(target)
    except OverflowError as exc:
        raise ValueError('Translated coordinates exceed native float storage') from exc
    return result
