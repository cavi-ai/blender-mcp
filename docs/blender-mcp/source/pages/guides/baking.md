# Bake maps

`bake` writes a normal or ambient-occlusion map to a new workspace `.png`.
It requires a `lease_id`.

## Inputs

| Parameter | Meaning |
| --- | --- |
| `map` | `normal` or `ao` |
| `name` | Low-poly target mesh |
| `path` | New workspace `.png` path |
| `high` | Optional 1–64 high-poly meshes for selected-to-active baking |
| `resolution` | 64–4096, default 1024 |
| `samples` | 1–256, default 16 |
| `margin` | 0–64 pixels, default 4 |
| `cage_extrusion` | 0–1, default 0.01 |
| `max_ray_distance` | 0–10, default 0.1 |
| `normal_space` | `tangent` or `object`; normal bakes only |
| `uv_layer` | Bake target UV layer; defaults to the render-active layer |
| `isolate` | Hide unrelated renderable objects, default true |

## Behavior

- Low and high meshes must be unmodified and free of shape keys.
- The low mesh needs an existing UV layer and at most 200,000 triangles.
- High-poly sources are limited to one million total triangles and 64 objects.
- Baking copies the low mesh and uses Cycles on CPU.
- Scene state, selection, materials and visibility are restored afterward.

The result reports the file path, byte count, SHA-256, map, resolution, samples,
margin, cage, ray distance, normal space, UV layer, low and high names, and
whether selected-to-active and isolation were used.

Curvature and lightmap baking are not implemented yet.

## Related

- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
