"""Bounded connected components of classified violating garment vertices."""


def summarize(vertices, triangles, evaluated_vertices, processed_vertices):
    parent = {index: index for index in vertices}

    def find(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for triangle in triangles:
        a, b, c = (int(index) for index in triangle)
        for first, second in ((a, b), (b, c), (c, a)):
            if first in vertices and second in vertices and vertices[first][1] == vertices[second][1]:
                x, y = find(first), find(second)
                if x != y:
                    parent[max(x, y)] = min(x, y)
    components = {}
    for index, (gap, region) in vertices.items():
        root = find(index)
        if root not in components:
            components[root] = []
        components[root].append((gap, index, region))
    patches = []
    for members in components.values():
        members.sort(key=lambda item: (item[0], item[1]))
        gap, index, region = members[0]
        patches.append({'vertex_count': len(members), 'min_clearance_m': gap,
                        'worst_vertex': index, 'region_ids': list(region),
                        'seeds': [{'vertex_index': vertex, 'clearance_m': value}
                                  for value, vertex, _ in members[:8]]})
    patches.sort(key=lambda patch: (patch['min_clearance_m'], patch['worst_vertex']))
    return {'total_patches': len(patches), 'violating_vertices': len(vertices),
            'evaluated_vertices': evaluated_vertices, 'processed_vertices': processed_vertices,
            'vertex_scan_complete': evaluated_vertices is not None and processed_vertices == evaluated_vertices,
            'truncated': len(patches) > 32, 'patches': patches[:32]}
