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
| `instance` | Scene collection instance containing internal mesh targets |
| `link_mode` | DATA binding or OBJECT override; updates preserve omitted modes |

Base color and emission use sRGB. Normal, roughness, metallic and alpha use
Non-Color.

## Requirements

- DATA assignment needs single-user mesh data; OBJECT overrides retain shared geometry.
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

## Material variants inside a kit

Inspect the collection instance with `scene_info(name=..., definition=true)`.
Each member reports material slot indices, names and DATA/OBJECT link modes.
Pass the internal mesh `names` and scene `instance` to `assign_material` to bind
its finish without linking source meshes into the scene.

Use `link_mode="OBJECT"` for a per-object override on shared mesh geometry. Use a
new `material_name` for a separate finish; changing an existing material changes
its users. For a kit variant, branch the definition with `object_edit make_unique`
first. DATA binding remains available for single-user mesh data. An
`update_existing` call preserves each target's current mode when `link_mode` is
omitted.

The response's `bindings` identifies the actual mode, mesh and mesh user count.
When an empty shared mesh needs its first slot, an empty data slot is reserved;
other users remain unassigned. `reserved_empty_slots` identifies these meshes.
Assignment failures restore previous slot modes and materials, including an
initially empty slot list.

Keep the authored UV and texture-role contract. Color/emission inputs use sRGB;
normal, roughness, metallic and alpha inputs use Non-Color. Save/reopen the
consumer, inspect the bindings and compare the evaluated material in the assembly
export. A Geometry Nodes Set Material node can supply generated surfaces through
its own exposed material control; use `geometry_nodes` for that control.
