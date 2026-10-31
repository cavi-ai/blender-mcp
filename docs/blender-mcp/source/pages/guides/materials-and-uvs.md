# Materials and UVs

`assign_material` binds a PBR material to exact mesh slots and packs bounded
workspace PNG or JPEG maps.

## Inputs

| Parameter | Purpose |
| --- | --- |
| `names` | 1–32 unique mesh names |
| `material_name` | New or existing material name |
| `base_color_texture`, `base_color` | sRGB base color map or scalar RGBA |
| `normal_texture`, `normal_strength` | Non-Color normal map and strength |
| `roughness_texture`, `roughness` | Non-Color map or scalar |
| `metallic_texture`, `metallic` | Non-Color map or scalar |
| `emission_texture`, `emission_strength` | sRGB emission map and strength |
| `alpha_texture`, `alpha_mode` | Non-Color alpha map and opaque, clip or blend mode |
| `uv_scale`, `uv_offset`, `uv_rotation_degrees` | One Mapping node for all maps |
| `update_existing` | Edit a material created by this tool and bound to the slot |
| `slot` | Material slot 0–31 |

Base color and emission use sRGB. Normal, roughness, metallic and alpha use
Non-Color.

## Requirements

- Meshes need single-user data.
- Textured assignment needs an existing UV layer.
- Each image is at most 16 MiB and 4096². The combined budget is 32 million
  pixels.
- The requested slot must exist, unless it is slot 0 on a mesh with no slots.

## Updating

`update_existing=true` preserves unspecified settings and replaces supplied maps.
The material must carry this tool's configuration tag and must be bound to the
requested slot. Untagged materials are refused, and maps cannot be removed.

## Verification

Run `inspect_mesh_quality` with `checks=["materials"]`. It reports PBR bindings,
expected color spaces, packed state, resolution consistency, unsupported graph
state and UV transforms.

Run `review_sheet` with `mode="uv_checker"` to inspect UV layout visually, or
`mode="texel_heatmap"` to see faces below, on and above a target density.

## Related

- [Prepare meshes](mesh-preparation.md)
- [Preview and review](previews-and-review.md)
- [Bake maps](baking.md)
