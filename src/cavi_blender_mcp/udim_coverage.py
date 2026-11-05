"""Bounded positive-area source UV coverage of a declared UDIM tile set."""

import math

import numpy as np

from .uv_layout import MAX_TRIANGLES, default_budget, triangle_intersection_area

REPORT_LIMIT = 1000
EXAMPLE_LIMIT = 32


def analyze(triangles, tiles, comparison_budget=None, unavailable_tiles=()):
    data = np.asarray(triangles, dtype=float)
    if data.ndim != 3 or data.shape[1:] != (3,2) or not 1 <= len(data) <= MAX_TRIANGLES:
        raise ValueError('Provide 1..20000 UV triangles')
    if comparison_budget is None:
        comparison_budget = default_budget(len(data))
    if (any(type(t) is not int or t < 1001 for t in tiles)
            or len(set(tiles)) != len(tiles) or not set(unavailable_tiles) <= set(tiles)):
        raise ValueError('Provide unique UDIM numbers and their unavailable subset')
    if type(comparison_budget) is not int or not 1 <= comparison_budget <= 1000000:
        raise ValueError('Comparison budget must be from 1 to 1000000')
    declared, required, unavailable_set = set(tiles), set(), set(unavailable_tiles)
    examples, issue_count = [], 0
    counts = {'nonfinite_triangles':0, 'degenerate_triangles':0, 'outside_domain_triangles':0}
    comparisons, done, complete = 0, 0, True

    def issue(kind, index, **extra):
        nonlocal issue_count
        issue_count += 1
        if len(examples) < EXAMPLE_LIMIT:
            examples.append({'kind':kind, 'triangle':index, **extra})

    for index, triangle in enumerate(data):
        if not np.isfinite(triangle).all():
            counts['nonfinite_triangles'] += 1
            issue('nonfinite_uv', index)
            done += 1
            continue
        a, b = triangle[1]-triangle[0], triangle[2]-triangle[0]
        if float(a[0]*b[1]-a[1]*b[0]) == 0:
            counts['degenerate_triangles'] += 1
            issue('degenerate_uv', index)
            done += 1
            continue
        low, high = triangle.min(axis=0), triangle.max(axis=0)
        if low[0] < 0 or high[0] > 10 or low[1] < 0:
            counts['outside_domain_triangles'] += 1
            issue('outside_udim_grid', index)
        left, right = max(0, math.floor(low[0])), min(10, math.ceil(high[0]))
        bottom, top = max(0, math.floor(low[1])), math.ceil(high[1])
        if left >= right or bottom >= top:
            done += 1
            continue
        exhausted = False
        for v in range(bottom, top):
            for u in range(left, right):
                if comparisons == comparison_budget:
                    exhausted = True
                    break
                comparisons += 1
                cell = np.asarray([(u,v),(u+1,v),(u+1,v+1),(u,v+1)], dtype=float)
                area = (triangle_intersection_area(triangle, cell[[0,1,2]])
                        + triangle_intersection_area(triangle, cell[[0,2,3]]))
                if area > 0:
                    number = 1001+u+10*v
                    required.add(number)
                    if number not in declared:
                        issue('missing_tile', index, tile=number)
                    elif number in unavailable_set:
                        issue('unavailable_tile', index, tile=number)
            if exhausted:
                break
        if exhausted:
            complete = False
            issue('budget_exhausted', index)
            break
        done += 1
    missing = required-declared
    unavailable = required & unavailable_set
    result = {'complete':complete,
        'passed':complete and not (missing or unavailable or any(counts.values())),
        'triangles':len(data), 'triangles_complete':done,
        'candidate_comparisons':comparisons, 'comparison_budget':comparison_budget,
        'area_rule':'positive_area', 'udim_columns':10,
        'examples':examples, 'issue_count':issue_count, 'examples_truncated':issue_count > len(examples), **counts}
    for label, values in [('required',required),('missing',missing),('unavailable',unavailable),
                          ('unused',declared-required if complete else None)]:
        ordered = sorted(values) if values is not None else None
        result[label+'_tiles'] = ordered[:REPORT_LIMIT] if ordered is not None else None
        result[label+'_tile_count'] = len(ordered) if ordered is not None else None
        result[label+'_tiles_truncated'] = ordered is not None and len(ordered) > REPORT_LIMIT
    return result
