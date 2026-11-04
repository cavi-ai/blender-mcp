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
extension and other settings. The image is a packed single-file binding; it does
not define a UDIM set or image-sequence delivery. `image_source` reports the exact
snapshot SHA-256 and byte count. `changed_image` distinguishes replacements from
unchanged packed snapshots, which are reused. A changed file at the same path is
loaded from a fresh snapshot, bypassing stale image-cache contents.

A failed edit restores the old image binding and managed tags and removes the
new image. Effective replacements use the same managed-configuration handoff as
socket edits. Save/reopen, inspect the binding, and review the authored material
before adapting it for the destination game shader.
