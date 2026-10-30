"""Physical triangle-to-texture measurements; no application dependency."""

import math


def measure_triangle(points, uv, resolution):
    if len(points) != 3 or any(len(point) != 3 for point in points):
        raise ValueError("Expected three 3D points")
    if uv is not None and (len(uv) != 3 or any(len(point) != 2 for point in uv)):
        raise ValueError("Expected three UV points")
    coordinates = [component for point in points for component in point]
    coordinates += [component for point in (uv or []) for component in point]
    if any(not math.isfinite(value) or abs(value) > 1e6 for value in coordinates):
        raise ValueError("Coordinates must be bounded and finite")
    if len(resolution) != 2 or any(type(v) is not int or not 1 <= v <= 4096 for v in resolution):
        raise ValueError("Texture dimensions must be integers from 1 to 4096")
    a, b = ([points[index][axis] - points[0][axis] for axis in range(3)] for index in (1, 2))
    cross = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    double_area = math.sqrt(sum(value * value for value in cross))
    result = {
        "world_area_m2": double_area / 2,
        "uv_area": None,
        "signed_uv_area": None,
        "density": None,
        "anisotropy": None,
    }
    if uv is None:
        return result
    u, v = ([uv[index][axis] - uv[0][axis] for axis in range(2)] for index in (1, 2))
    result["signed_uv_area"] = (u[0] * v[1] - u[1] * v[0]) / 2
    result["uv_area"] = abs(result["signed_uv_area"])
    if double_area <= 2e-12 or result["uv_area"] <= 1e-12:
        return result
    length = math.sqrt(sum(value * value for value in a))
    along = sum(x * y for x, y in zip(a, b)) / length
    across = double_area / length
    # Jacobian from an orthonormal world tangent basis to actual texture pixels.
    j00, j10 = u[0] * resolution[0] / length, u[1] * resolution[1] / length
    j01 = (v[0] * resolution[0] - j00 * along) / across
    j11 = (v[1] * resolution[1] - j10 * along) / across
    determinant = result["uv_area"] * resolution[0] * resolution[1] / result["world_area_m2"]
    trace = j00 * j00 + j01 * j01 + j10 * j10 + j11 * j11
    largest = math.sqrt(
        (trace + math.sqrt(max(0, trace * trace - 4 * determinant * determinant))) / 2
    )
    smallest = determinant / largest
    result.update(density=math.sqrt(determinant), anisotropy=max(1, largest / smallest))
    return result


def summarize(samples):
    valid = [sample for sample in samples if sample["density"] is not None]
    total_area = sum(sample["world_area_m2"] for sample in samples)
    mapped_area = sum(sample["world_area_m2"] for sample in valid)

    def quantile(fraction):
        accumulated = 0
        for sample in sorted(valid, key=lambda value: value["density"]):
            accumulated += sample["world_area_m2"]
            if accumulated >= mapped_area * fraction:
                return sample["density"]
        return None

    return {
        "triangles": len(samples),
        "world_area_m2": total_area,
        "mapped_area_m2": mapped_area,
        "mapping_coverage": mapped_area / total_area if total_area else None,
        "uv_area_sum": sum(sample["uv_area"] or 0 for sample in samples),
        "world_degenerate_triangles": sum(sample["world_area_m2"] <= 1e-12 for sample in samples),
        "uv_missing_triangles": sum(sample["uv_area"] is None for sample in samples),
        "uv_degenerate_triangles": sum(
            sample["uv_area"] is not None and sample["uv_area"] <= 1e-12 for sample in samples
        ),
        "negative_uv_orientation_triangles": sum(
            (sample["signed_uv_area"] or 0) < 0 for sample in samples
        ),
        "density_area_weighted": math.sqrt(
            sum(sample["density"] ** 2 * sample["world_area_m2"] for sample in valid) / mapped_area
        )
        if mapped_area
        else None,
        "density_min": min((sample["density"] for sample in valid), default=None),
        "density_max": max((sample["density"] for sample in valid), default=None),
        "density_p10": quantile(0.1),
        "density_p90": quantile(0.9),
        "anisotropy_max": max((sample["anisotropy"] for sample in valid), default=None),
    }
