# Bake maps

`bake` writes a normal, ambient-occlusion, curvature or lightmap map to a new
workspace `.png`. It requires a `lease_id`.

## Inputs

| Parameter | Meaning |
| --- | --- |
| `map` | `normal`, `ao`, `curvature` or `lightmap` |
| `name` | Low-poly target mesh |
| `path` | New workspace `.png` path |
| `high` | Optional 1–64 high-poly meshes for selected-to-active normal/AO baking |
| `resolution` | 64–4096, default 1024 |
| `samples` | 1–256, default 16; used by AO, curvature and lightmap |
| `margin` | 0–64 pixels, default 4 |
| `cage_extrusion` | 0–1, default 0.01; normal/AO only |
| `max_ray_distance` | 0–10, default 0.1; normal/AO only |
| `normal_space` | `tangent` or `object`; normal bakes only |
| `uv_layer` | Bake target UV layer; defaults to the render-active layer |
| `isolate` | Hide unrelated renderable objects, default true |

## Behavior

- Low and high meshes must be unmodified and free of shape keys.
- The low mesh needs an existing UV layer and at most 200,000 triangles.
- High-poly sources are limited to one million total triangles and 64 objects.
- Baking copies the low mesh and uses Cycles on CPU.
- Curvature is self-baked from Cycles pointiness; it does not take high-poly sources.
- Lightmap bakes direct and indirect diffuse lighting. Keep scene lights visible;
  `isolate` hides unrelated meshes but never lights.
- Normal and AO support selected-to-active high-poly sources.
- Scene state, selection, materials and visibility are restored afterward.

The result reports the file path, byte count, SHA-256, map, resolution, samples,
margin, cage, ray distance, normal space, UV layer, low and high names, and
whether selected-to-active and isolation were used.

## Related

- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
