# Materials and UVs

## Independent authored finishes

To branch an existing finish on selected scene meshes, call `assign_material`:

```json
{"action":"make_unique","names":["Lamp"],"material_name":"BlueGlaze","slot":0,"lease_id":"<claim-token>"}
```

The selected slots must have the same source material, and the new name must be
unused. Native material and nested shader-group copies preserve links, defaults,
interfaces and custom properties. Reused groups stay shared within the new graph
while becoming independent from the source graph. The default `OBJECT` binding
retains shared mesh geometry and other objects' finishes. Explicit `DATA` binding
requires single-user editable meshes.

Images, animation actions and scene-object references stay shared. Use `set_image`
to replace a variant's texture binding independently; copying a graph does not
duplicate texture pixels or animation actions. `material_copy` reports the source
and copied group mapping; `bindings` reports each target's actual slot mode.

Inspect the copy, compare matched renders before and after tuning, and save/reopen
the source. Failed copies restore slot bindings and remove their new material and
group data. Blender shader preservation still requires explicit adaptation to the
consuming game shader.

## Managed PBR assignment

`assign_material` with `action="assign"` builds a managed PBR material on exact
mesh slots and packs bounded workspace PNG or JPEG maps.

### Inputs

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
| `uv_layer` | Named UV map for texture coordinates and normal-map tangents; empty selects render-active UVs |
| `update_existing` | Edit a material created by this tool and bound to the slot |
| `slot` | Material slot 0–31 |
| `instance` | Scene collection instance containing internal mesh targets |
| `link_mode` | DATA binding or OBJECT override; updates preserve omitted modes |

Base color and emission use sRGB. Normal, roughness, metallic and alpha use
Non-Color.

Use `uv_layer="BakeAtlas"` to preview maps baked to that atlas while preserving
the mesh's active and render-active UV settings. The same named layer drives the
UV Map node and the tangent-space Normal Map node. Omit `uv_layer` to preserve a
managed material's current choice during updates; pass `""` to return to
render-active UVs. New materials use render-active UVs by default.

The named layer must exist on every target. Updating a shared material also
checks its other mesh owners before changing nodes or loading textures. Branch
the material first when its users need different UV contracts. This applies to
scene meshes, OBJECT overrides and collection-instance members.

### Requirements

- DATA assignment needs single-user mesh data; OBJECT overrides retain shared geometry.
- Textured assignment needs an existing UV layer.
- Each image is at most 16 MiB and 4096². The combined budget is 32 million
  pixels.
- The requested slot must exist, unless it is slot 0 on a mesh with no slots.

### Updating

`update_existing=true` preserves unspecified settings and replaces supplied maps.
The material must carry this tool's configuration tag and must be bound to the
requested slot. Untagged materials are refused, and maps cannot be removed.

### Verification

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

## Tune an authored shader graph

Use `assign_material(action="inspect", material_name="GlazedCeramic")` without an
edit lease to discover exact node names, native socket identifiers, values and
links. `offset` and `limit` page nodes; `node` selects one exact node. Links cover
edges touching the returned nodes. Image `decoded_depth_bits` describes Blender's
decoded image buffer; it does not establish the source file's sample precision.

Follow nested shader groups with `group_path`, an ordered list of group **node**
names from the material root. Inspect each level first. The response reports
`affected_materials`, their total and truncation state. Editing a shared group
changes all material users of that group. Root group-node inputs are per-material
controls; prefer those when a shared shader exposes the intended control.

After claiming ownership, edit only discovered socket identifiers:

```json
{"action":"set_inputs","material_name":"GlazedCeramic","group_path":["Finish Controls","Inner Layer"],"node":"Hero Surface","inputs":{"Coat Weight":0.4},"lease_id":"<claim-token>"}
```

Values use the native socket type and bounds. Colors are scene-linear, with no
implicit sRGB conversion. A linked socket's default is a fallback; changing it
preserves the incoming link and does not override the connected value. Neither
mode rebuilds nodes, changes images nor rewires connections. Validate the whole
batch before writing; a failed edit or receipt restores prior defaults and tags.

An effective native edit moves any affected tool-managed material configuration
to `cavi_material_config_source` as provenance and removes its rebuild tag. A
no-op retains the configuration. Continue authored edits with `set_inputs`;
`update_existing` refuses detached graphs rather than replacing the authored
nodes from stale settings. Other custom properties remain intact. Save to a new
blend, reopen it and compare values, links and the rendered finish. Blender's
native graph is source artwork; Unity delivery still needs a supported shader and
verified texture handoff.

### Value/RGB nodes and image replacement

Inspection includes native `outputs` as well as `inputs`. For Value or RGB control
nodes, call `set_inputs` with `node` and an `outputs` map keyed by the discovered
socket identifier. Inputs and outputs can be supplied together; the whole batch
is validated before writing. `changed_outputs` reports effective output-default
changes. Outputs computed by other nodes still follow their node evaluation;
a stored socket default does not replace that computation.

For an existing image-backed node, use `action="set_image"`:

```json
{"action":"set_image","material_name":"GlazedCeramic","group_path":["Finish Controls"],"node":"Pattern","image":{"path":"textures/glaze.exr","color_space":"Non-Color","alpha_mode":"CHANNEL_PACKED"},"lease_id":"<claim-token>"}
```

`image.path` selects an existing workspace file decoded by Blender. PNG, TIFF and
EXR retain their original encoded bytes and native precision; packing does not
re-encode them. Choose `color_space` explicitly from the active OCIO configuration.
`alpha_mode` is `STRAIGHT` (default), `PREMUL`, `CHANNEL_PACKED` or `NONE`.
Use Non-Color for data maps. Color maps require their actual source color space;
a linear EXR is not automatically sRGB.

A fresh image datablock keeps other nodes' images, color spaces, alpha modes and
unsaved pixels intact. The edited node keeps its links, interpolation, projection,
extension and other settings. Without `tiles`, the image is a packed single-file binding. Supply `tiles` for
a declared UDIM set as below; image-sequence delivery is separate. `image_source` reports the exact
snapshot SHA-256 and byte count. `changed_image` distinguishes replacements from
unchanged packed snapshots, which are reused. A changed file at the same path is
loaded from a fresh snapshot, bypassing stale image-cache contents.

A failed edit restores the old image binding and managed tags and removes the
new image. Effective replacements use the same managed-configuration handoff as
socket edits. Save/reopen, inspect the binding, and review the authored material
before adapting it for the destination game shader.

### Declared UDIM texture sets

Pass a filename pattern containing one `<UDIM>` token and the exact tile numbers:

```json
{"action":"set_image","material_name":"CharacterFinish","group_path":["Surface"],"node":"BaseColor","image":{"path":"textures/skin.<UDIM>.exr","tiles":[1001,1002,1011],"color_space":"Non-Color","alpha_mode":"CHANNEL_PACKED"},"lease_id":"<claim-token>"}
```

The filenames come from substituting each declared number into the pattern.
All files must resolve inside the workspace. Duplicate declarations, missing
files, invalid images and unsupported native tile layouts fail without replacing
the binding. Tile 1001 is optional; gaps and mixed resolutions are preserved.
Neighboring undeclared files are excluded from the native snapshot. Ensure the
declared set covers the asset's intended UVs; a missing UV tile still produces
Blender's missing-texture fallback. Keep the authored UV coordinates instead of
packing a UDIM source into one tile during validation.

`image_source.tiles` reports each tile's path, byte count and SHA-256.
`manifest_sha256` identifies the sorted tile manifest; it is not a file hash.
Inspection returns native tile sizes/channels and actual `packed_tiles` receipts.
Packing retains original file bytes, including high-precision PNG/TIFF/EXR.
The active image buffer's `decoded_depth_bits` is not every source tile's precision.
Logical paths remain aligned with the declared pattern even for internal symlinks.

Unchanged clean sets with matching packed bytes are reused. Changed source bytes
produce a fresh image while preserving other users and unsaved source pixels.
Failures restore the previous binding and managed tags and remove new IDs and
snapshots. Save/reopen the blend and check its tile table and hashes. A packed
material can be appended through `asset_library` without the external tile files.

UDIM authoring does not make a destination shader tile-aware. Declare the game's
supported texture layout and color/data roles before delivery. Preserve the
editable tiled source when making an explicit atlas or separate material sets;
verify the adapted result with the consuming renderer.

### Check source UV coverage

After binding a tiled image, copy its actual native image name from shader
inspection and check the mesh UV layer:

```json
{"names":["CharacterBody"],"udim_image":"skin.<UDIM>.exr","material":"CharacterFinish","uv_layer":"UVMap"}
```

These are `inspect_uv_layout` arguments. This mode needs neither texture
resolution nor padding inputs. It uses UV0 unless `uv_layer` is named, filters
faces using actual object material-slot bindings, and reads the source without
editing geometry, selection, images or ownership. Modifiers are not evaluated.

The scope is `source_uv_udim_coverage`. `coverage` reports required, missing,
unavailable and unused tiles, degenerate/nonfinite triangles, coordinates outside
the ten-column nonnegative UDIM grid, and affected object/face examples. A tile
is required when a UV triangle has positive intersection area with its cell;
boundary-only contact does not require a neighbor. Cells enclosed by a triangle
are included even when no vertex lies in them. Native tile buffers without
positive dimensions/channels are unavailable.

Require both `complete` and `coverage.passed`. Exhausted candidate budgets cannot
pass, and unused tiles are unknown (`null`) until analysis completes. Tile lists
are capped at 1000 and examples at 32, with exact counts and truncation flags.
Read `image.tile_count` and `tiles_truncated` when inspecting image metadata.

This is source UV-layer coverage, not shader-vector evaluation. Mapping nodes,
procedural coordinates, projections, exported/evaluated UVs, filtering, overlaps,
gutters and file precision require their corresponding checks. Verify that the
chosen layer is the one sampled by the material before using this result as part
of visual acceptance. Unique 0..1 overlap/gutter analysis remains available with
`texture_resolution` and `padding_pixels` instead of `udim_image`.

Shader inspection reports `uv_map` and `from_instancer` on UV Map nodes,
`vector_type` on Mapping nodes, and image-node `projection`/`extension` settings.
Follow the reported vector links before choosing a source layer. Mesh inspection
rows include `render_uv_layer` for comparison with an implicit active-UV source.
These settings are metadata; the coverage check does not evaluate a vector graph.
