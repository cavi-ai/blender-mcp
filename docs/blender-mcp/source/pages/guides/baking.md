# Bake maps

`bake` writes geometry maps or an explicitly selected shader channel to a new
workspace image. It requires a `lease_id`.

## Inputs

| Parameter | Meaning |
| --- | --- |
| `map` | `normal`, `ao`, `curvature`, `lightmap` or `shader` |
| `name` | Low-poly target mesh |
| `path` | New workspace `.png`; `shader` also accepts `.exr` |
| `high` | Optional 1–64 high-poly meshes for selected-to-active normal/AO baking |
| `resolution` | 64–4096, default 1024 |
| `bit_depth` | PNG: 8/16, default 16. Shader EXR: 16/32, default 32 |
| `source` | Shader only: material, group path, node, socket identifier, INPUT/OUTPUT direction and data/color role |
| `samples` | 1–256, default 16; used by AO, curvature and lightmap |
| `margin` | 0–64 pixels, default 4 |
| `cage_extrusion` | 0–1, default 0.01; normal/AO only |
| `max_ray_distance` | 0–10, default 0.1; normal/AO only |
| `normal_space` | `tangent` or `object`; normal bakes only |
| `uv_layer` | Bake target UV layer; defaults to the render-active layer |
| `isolate` | Hide unrelated renderable objects, default true |

## Geometry maps

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

## Authored shader channels

Inspect `assign_material` with `action: inspect` to select exact node names and
socket identifiers. Choose a numeric, color or vector socket, not a BSDF/shader
socket. Select the authored channel explicitly: a diffuse-light bake is not a
general recovery of base color, metallic or roughness.

```json
{
  "map": "shader", "name": "Lamp", "path": "lamp-roughness.png",
  "source": {
    "material": "Glaze", "group_path": ["Finish Controls"],
    "node": "Surface", "socket": "Roughness", "direction": "INPUT", "role": "data"
  },
  "uv_layer": "BakeAtlas", "resolution": 2048, "lease_id": "<claim-token>"
}
```

An input evaluates its connected source or unlinked default, including the
selected nested group's instance inputs. Color/vector output uses RGB; select
an alpha or scalar socket separately when needed. Socket conversions follow
Blender's shader evaluation. View-dependent shader values need a deliberate
downstream approximation; this does not translate an entire shader graph.

The source material must cover faces on the named scene mesh. Only those faces
write the image. Choose a unique 0..1 target UV atlas; keep a tiled or UDIM shader
UV layer as the render-active layer. `uv_layer` controls rasterization without
replacing the shader's UV coordinates. Use `inspect_uv_layout` unique-UV checks
for overlap and gutter acceptance before baking. The atlas bound check alone
does not prove unique UVs.

The original actor is evaluated at the current frame, preserving object identity,
shared mesh data, shape keys and modifiers. Temporary object material overrides
and private shader/group copies isolate the bake. Cycles CPU emission passes
retain positive and negative samples before encoding. Scene bake settings,
bindings, selection and visibility are restored, including after encoder failure.
This shader path does not use high-poly projection, cage or normal-space options.

- `role: data` writes raw Non-Color values. Color PNG uses the sRGB transfer
  without the scene's artistic view transform. Color EXR remains scene-linear.
- PNG requires every sampled RGB value within 0..1. Signed/HDR channels require
  EXR; values are never silently clipped into PNG.
- EXR defaults to full 32-bit float. Explicit half-float output rejects values
  outside its finite range. Choose final runtime compression separately.
- The receipt adds the selected `source`, RGB channels, sampled minimum/maximum,
  actual output color space and file hash. Retain this with the source `.blend`.

Updated bake calls require an updated Blender bridge. An older bridge is refused
before writing a file. Preserve its scene and restart only the task-owned bridge
with the updated package; do not repeatedly retry an uncertain bake.

## Related

- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
