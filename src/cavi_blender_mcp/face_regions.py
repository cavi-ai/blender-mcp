"""Deterministic source-face connectivity; ambiguous edges are boundaries."""


def component(seed,count,edge_faces,blocked):
    if type(seed) is not int or not 0<=seed<count:
        raise ValueError('region.seed must identify a current source face')
    adjacent=[[] for _ in range(count)]
    for index,faces in enumerate(edge_faces):
        if index in blocked or len(faces)!=2 or faces[0]==faces[1]:
            continue
        first,second=faces
        adjacent[first].append(second)
        adjacent[second].append(first)
    found,pending={seed},[seed]
    while pending:
        for neighbor in adjacent[pending.pop()]:
            if neighbor not in found:
                found.add(neighbor)
                pending.append(neighbor)
    return sorted(found)
