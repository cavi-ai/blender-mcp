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
| `bit_depth` | PNG channel precision, 16 by default; 8 only when explicitly selected |
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
- Baking copies the low mesh and uses Cycles on CPU with a floating-point image buffer.
- All copied faces use one private material/image target. Source texture buffers,
  material slots, object overrides and linked mesh data remain unchanged. Empty
  or untextured source slots do not need active image nodes.
- Output uses the requested PNG depth without an intermediate 8-bit image.
- Normal, AO and curvature values remain raw linear data. Lightmaps use the sRGB
  transfer, without the current scene's artistic view transform, exposure or gamma.
- Normal RGB channels are always +X, +Y, +Z; tangent normals use OpenGL orientation.
  Existing scene channel swizzles are restored afterward.
- Curvature is self-baked from Cycles pointiness; it does not take high-poly sources.
- Lightmap bakes direct and indirect diffuse lighting. Keep scene lights visible;
  `isolate` hides unrelated meshes but never lights.
- Normal and AO support selected-to-active high-poly sources.
- Scene state, selection, materials and visibility are restored afterward.

The result reports the file path, byte count, SHA-256, map, resolution, samples,
margin, cage, ray distance, normal space, UV layer, low and high names, and
whether selected-to-active and isolation were used. It also declares `bit_depth`,
`color_space` and `normal_channels`. Preserve the source precision through packing
and choose a consuming runtime format explicitly.

Updated bake calls require an updated Blender bridge. An older bridge is refused
before writing a file. Preserve its scene and restart only the task-owned bridge
with the updated package; do not repeatedly retry an uncertain bake.

## Related

- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
