"""Plan translations using the coordinate storage of the native mesh."""
import math
from array import array
from heapq import heapify, heappop, heappush
from itertools import product

from .mesh_regions import indices, selection


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
    weights = [1.]*len(rows) if weights is None else weights
    if (len(weights) != len(rows)
            or any(type(w) not in (int,float) or not math.isfinite(w) or not 0 <= w <= 1 for w in weights)):
        raise ValueError('Vertex weights must match the selected points and lie within 0..1')
    selection([0],offset)
    return displaced(rows, [tuple(v*w for v in offset) for w in weights])


def displaced(rows, offsets):
    result = []
    if len(rows) != len(offsets):
        raise ValueError('Every vertex requires its corresponding displacement')
    try:
        for point,offset in zip(rows,offsets,strict=True):
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


def symmetric_offsets(vertices, edges, seeds, offset, axis, tolerance_m, *, radius=None,
                      linear=((1,0,0),(0,1,0),(0,0,1)),unit_m=1.,max_affected=20000):
    """Reflect one hemisphere's displacement; retain the source's positional asymmetry."""
    tolerance_m = radius_m(tolerance_m)
    if axis not in ('X','Y','Z'):
        raise ValueError('Symmetry requires local X, Y or Z')
    if (not 1 <= len(vertices) <= 500000 or type(max_affected) is not int
            or not 1 <= max_affected <= 20000):
        raise ValueError('Symmetry supports 500000 source vertices and 20000 affected vertices')
    selection(seeds,offset,len(vertices),field='vertex_indices')
    if (len(linear) != 3 or any(len(row) != 3 for row in linear)
            or any(type(v) not in (int,float) or not math.isfinite(v) for row in linear for v in row)
            or type(unit_m) not in (int,float) or not math.isfinite(unit_m) or unit_m <= 0
            or any(len(p) != 3 or any(type(v) not in (int,float) or not math.isfinite(v) for v in p)
                   for p in vertices)):
        raise ValueError('Symmetry requires finite source coordinates and world metric')
    a,b,c = linear
    determinant = a[0]*(b[1]*c[2]-b[2]*c[1])-a[1]*(b[0]*c[2]-b[2]*c[0])+a[2]*(b[0]*c[1]-b[1]*c[0])
    if not math.isfinite(determinant) or determinant == 0:
        raise ValueError('Symmetry requires a nonsingular world transform')
    dimension = 'XYZ'.index(axis)
    axis_m = math.hypot(*(row[dimension]*unit_m for row in linear))

    def physical(point):
        result = tuple(sum(row[i]*point[i] for i in range(3))*unit_m for row in linear)
        if any(not math.isfinite(v/tolerance_m) for v in result):
            raise ValueError('Symmetry metric exceeds finite matching precision')
        return result

    def mirrored(point):
        return tuple(-v if i == dimension else v for i,v in enumerate(point))

    center = [abs(p[dimension])*axis_m <= tolerance_m/2 for p in vertices]
    sides = {1 if vertices[i][dimension] > 0 else -1 for i in seeds if not center[i]}
    if len(sides) > 1:
        raise ValueError('Select symmetry seeds on one side of the local origin plane')
    side = next(iter(sides),1)
    if radius is not None:
        def hemisphere_edges():
            for count,edge in enumerate(edges,1):
                if (count > 1500000 or len(edge) != 2
                        or any(type(i) is not int or not 0 <= i < len(vertices) for i in edge)):
                    raise ValueError('Symmetry supports 1500000 valid source edges')
                if all(center[i] or vertices[i][dimension]*side > 0 for i in edge):
                    yield edge
        influence = geodesic_weights(vertices,hemisphere_edges(),seeds,radius,
            linear=linear,unit_m=unit_m,max_affected=max_affected)
    else:
        influence = [(i,1.) for i in sorted(seeds)]
    coordinates = [physical(p) for p in vertices]
    grid = {}
    for i,p in enumerate(coordinates):
        cell = tuple(math.floor(v/tolerance_m) for v in p)
        grid.setdefault(cell,[]).append(i)
    comparisons = 0

    def counterpart(index):
        nonlocal comparisons
        target = physical(mirrored(vertices[index]))
        cell = tuple(math.floor(v/tolerance_m) for v in target)
        found = []
        for delta in product((-1,0,1),repeat=3):
            for candidate in grid.get(tuple(a+b for a,b in zip(cell,delta,strict=True)),()):
                comparisons += 1
                if comparisons > 2000000:
                    raise ValueError('Symmetry matching exceeds 2000000 candidate comparisons')
                if math.dist(target,coordinates[candidate]) <= tolerance_m:
                    found.append(candidate)
                    if len(found) > 1:
                        raise ValueError(f'Ambiguous symmetry counterpart for source vertex {index}')
        if not found:
            raise ValueError(f'Missing symmetry counterpart for source vertex {index}')
        return found[0]

    offsets,weights,pairs = {},{},[]
    max_error = 0.
    for index,weight in influence:
        partner = counterpart(index)
        if counterpart(partner) != index or center[index] != (partner == index):
            raise ValueError('Symmetry counterparts must be reciprocal and unambiguous')
        vector = tuple(0. if center[index] and i == dimension else v*weight for i,v in enumerate(offset))
        offsets[index],weights[index] = vector,weight
        offsets[partner],weights[partner] = mirrored(vector),weight
        pairs.append([index,partner])
        max_error = max(max_error,math.dist(physical(mirrored(vertices[index])),coordinates[partner]))
        if len(offsets) > max_affected:
            raise ValueError('Symmetry exceeds the combined affected-vertex budget')
    if not any(any(v) for v in offsets.values()):
        raise ValueError('Center-plane symmetry requires a tangential displacement')
    return dict(sorted(offsets.items())), {'axis':axis,'plane_local':0.,'tolerance_m':tolerance_m,
        'source_side':side,'pairs':pairs[:64],'pairs_truncated':len(pairs)>64,
        'max_pair_error_m':max_error,'policy':'reflect_displacement_preserve_source_asymmetry'},dict(sorted(weights.items()))
