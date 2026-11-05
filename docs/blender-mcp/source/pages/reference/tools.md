# Tools

The server publishes 20 tools. Every mutation requires a `lease_id` unless the
tool is listed as lease-free.

Lease-free tools: `scene_info`, `inspect_mesh_quality`, `inspect_uv_layout`, `inspect_rig`,
`render_preview`, `review_sheet` and `session_control`. `asset_io` generation
also runs without a lease, but import, export and save do not.
`assign_material` `inspect` is lease-free; `set_inputs` requires ownership. Inspect
native shader inputs/outputs and shared owners before tuning defaults through nested
`group_path` nodes. `set_image` replaces an image binding with a packed native
workspace snapshot and explicit color/alpha interpretation. Optional `image.tiles`
declares an exact UDIM set for an `<UDIM>` filename pattern. See [authored shader controls](../guides/materials-and-uvs.md#tune-an-authored-shader-graph).

For a nested kit definition, `scene_info(name=..., definition=true)` pages through
its source objects. `geometry_nodes` inspect/set_inputs accepts `instance` to
resolve an internal member through that scene instance. Edits affect the shared
definition; the ordinary scene-object route remains unchanged.

`object_edit` `make_unique` takes a scene collection instance's `name`, a unique
collection `new_name` and lease. It branches the current editable definition and
retargets that placement, returning actual source/copy ID mappings.

`assign_material` accepts `instance` for internal mesh targets and `link_mode`
(DATA/OBJECT) for slot binding. Object overrides retain shared geometry; omitted
modes on updates preserve existing links. Definition pages report `material_slots`.

## asset_library

`inspect` is lease-free; `append` requires a lease. Paths are workspace `.blend`
files. Select `kind`: `objects`, `collections` (default), `materials` or `node_groups`.
Inspection accepts `offset` and `limit` (1–1000, default 100); it returns exact
names, source SHA-256 and byte size without loading IDs into the scene.

`append` requires 1–256 unique `names` and the inspected `expected_sha256`.
Blender appends independent local IDs recursively, preserving asset metadata,
rigs and procedural graphs. Name collisions receive native suffixes. `roots`
and `items` map source names to actual imported names through native import
events; never infer names from suffixes. `items` is capped at 1000 with an explicit
truncation flag. `created_counts` covers all newly created IDs.
For collection placements, `instance_collections=true` returns instance object
names in `instances`; see [collection assemblies](../guides/collection-assembly.md).

The current project, selection and active collection are preserved. Failures
remove newly appended IDs; inspect after any uncertain result. Packed image
receipts hash every packed file; external image files must exist inside the
workspace and are hashed without conversion. See [native libraries](../guides/native-libraries.md).

## geometry_nodes

`inspect` is lease-free. `set_inputs` and `bake_copy` require a lease.

| Parameter | Used by |
| --- | --- |
| `name` | Existing procedural object |
| `modifier` | Optional exact modifier for `inspect`, required for `set_inputs` |
| `inputs` | Socket identifier to typed value; omitted values are preserved |
| `attributes` | Socket identifier to attribute name; null disables attribute mode |
| `new_name` | `bake_copy`; independent static mesh of the evaluated stack at the current frame |

Read socket identifiers, types, ranges, values and field modes before edits.
Datablock values use `{name, id_type}` or null. Source node groups remain shared
and unchanged; values belong to the named object's modifier. The full batch is
validated before assignment; a native setter or value mismatch restores prior
values. Inputs driven by animation still follow that animation when time changes.

`bake_copy` preserves evaluated mesh layers, material slots and world transform.
It reports fractional frame time, triangle counts and triangle usage per material
slot. It captures the mesh component; curves and volumes need conversion in the
source graph. Unrealized instances fail before allocation; use Realize Instances
in the graph or the existing instance-preserving export instead. The source is
preserved. See [procedural variants](../guides/procedural-assets.md).

## scene_info

Read-only. Returns Blender version, file, workspace, collection tree and a page
of objects. Mesh objects report `shape_keys`, `shape_key_names` and the
active `shape_key_action`.

Scene inventory responses include `bridge.protocol` and `bridge.build`, identifying
the implementation loaded inside Blender. `runtime status` compares this identity
with the installed server and exits nonzero on a mismatch. Preserve the project
and edit ownership before refreshing an outdated bridge.

`source_state.saved_source` retains the saved path, SHA-256 and byte count captured
at bridge startup or the latest load/save event. It remains unchanged when a file
is replaced externally. Compare it with the declared production source and require
`source_state.dirty=false` before deriving exports from that saved revision.

| Parameter | Values |
| --- | --- |
| `name` | Optional exact object name; returns that object only |
| `limit` | 1–1000, default 200 |
| `offset` | Nonnegative page offset |

## inspect_mesh_quality

Read-only. Measures exact static mesh names.

| Parameter | Values |
| --- | --- |
| `names` | 1–32 unique mesh names |
| `texture_resolution` | Two integers 1–4096, default `[1024, 1024]` |
| `uv_layer` | Optional render-active override |
| `checks` | Any of `naming`, `topology`, `lightmap`, `transforms`, `origin`, `materials` |
| `naming` | `mesh_prefix`, `lod_suffix`, `collision_prefixes` |
| `lightmap_uv` | UV layer name, default `UVMap_Lightmap` |
| `lightmap_resolution` | 16–4096, default 64 |

Refuses modifiers, shape keys and rigs.

## inspect_uv_layout

Read-only source UV preflight. Treats the exact selected meshes as **one texture
set**, including overlaps between objects. Pass `material` to select faces using
one exact material across objects and slots, including multi-material meshes.
Without a filter, all faces are measured together.

| Parameter | Values |
| --- | --- |
| `names` | 1–32 unique Object Mode mesh names |
| `texture_resolution` | Required width and height, each 1–16384 |
| `padding_pixels` | Required minimum chart separation and tile-border clearance, 0–256 pixels |
| `uv_layer` | Optional exact name; default is layer **index 0** |
| `comparison_budget` | 1–1000000 candidate comparisons; default 100000 |
| `material` | Optional exact material name; at least one source face must use it |

Up to 20000 selected triangles and 200000 source vertices per call, with at most
60000 loops per mesh. Modifiers and shape keys are not evaluated; this works on
raw static or skinned source UVs. Object ranges and selected UV layer indices
identify every reported triangle. Selection, geometry, UVs and edit ownership
are unchanged. Each object also reports its full source triangle count and used
material slots with per-slot counts, allowing callers to check texture-set
coverage. UV readiness applies only to the selected faces.

Triangle intersections use polygon clipping, including subpixel overlaps;
shared edges have zero overlap area. `overlap.pairwise_area_pixels2` sums areas
across pairs, so triple overlaps are counted repeatedly. It is not atlas occupancy.
Charts connect across shared source edges with exactly matching loop UVs.
Disconnected but touching charts have zero clearance. Padding uses pixel-space
triangle distances, accounting for nonsquare textures. Examples are capped at 32;
counts include all measured pairs.

`complete=false` means the comparison budget was exhausted: counts are lower
bounds, never evidence of absence. `unique_tile_ready` is false for incomplete
analysis, nonfinite/degenerate/out-of-tile UVs, positive-area overlaps or insufficient
requested padding. It applies only to a unique 0..1 tile. Intentional tiled,
mirrored and stacked mappings need their own policy. Area tolerance is 1e-8 pixel²;
padding tolerance is 1e-6 pixel. No raster occupancy approximation is used here.

Choose padding from bake dilation, filtering and mip requirements. The tool does
not validate the cage, projection, final baked maps, material transforms or
exported UVs. Verify those separately before accepting the asset.

## inspect_rig

Read-only. Reports hierarchy, linked clips and skin weights.

| Parameter | Values |
| --- | --- |
| `armature` | Exact armature name |
| `meshes` | 1–8 unique mesh names |
| `max_influences` | 1–32, default 4 |
| `action` | Optional action name to analyze |
| `checks` | `root_motion`, `loop`, `deformation` |
| `samples` | 2–32, default 8 |

Each mesh needs one vertex-group Armature modifier bound to that rig. With
`checks`, the call samples the named or active action and restores the action,
pose and frame afterward.

## compare_rig_motion

Read-only. Compares the current evaluated source and candidate timelines at 2–32
samples, restoring the frame and subframe afterward. Supply exact armatures,
1–8 `{source, candidate}` skin pairs, integer `start_frame`/`end_frame`, and an
explicit `max_error_m` in metres. Both rigs must use the same scene unit scale.

`vertex_match: index` compares corresponding vertices for an unchanged bake copy.
Use `point_set` after export, where UV seams can duplicate vertices; it measures
bidirectional nearest-point distance and does not establish topology equivalence.
`candidate_frame_offset` handles a measured imported clip start offset.
`space: start_root` removes each rig's initial placement; `world` preserves it.

Reports maximum/RMS skin errors, bone-head errors and sampled motion magnitude.
Missing or extra bones fail comparison. Unsampled times, bone roll/tail
reconstruction, normals, foot contact and Unity import need separate review.

## inspect_skin_clearance

Read-only. Samples evaluated garment vertices and, by default, triangle centres
against closed body components. Supply `body`, 1–8 distinct `garments`, increasing
`start_frame`/`end_frame`, and an explicit `min_clearance_m`. `samples` is 2–32.
`surface_samples: vertices` omits face-centre probes. `max_queries` bounds nearest,
component and ray queries (default/maximum 1,000,000); surface samples are capped
at four million. The call restores frame and subframe.

Reports signed gaps in metres, inside/violating/ambiguous counts, worst frames and
probe indices, body topology and numerical resolution. Multiple closed body
components are treated as a union. Ray parity does not depend on face winding.
Coordinates are normalized around the body before native BVH queries.

`complete` and `passed` must both be true. Open or degenerate bodies, exhausted
budgets and ambiguous ray/contact classifications cannot pass. A closed skinned
reference cage can be used when the visible body has intentional openings.

These are sampled clearance measurements. They do not certify every triangle
or time, body self-intersections, cloth simulation or engine behavior. Review
reported joints and morph combinations visually before accepting the asset.

## rig_edit

Mutating. Actions: `create`, `bind`, `weights`, `pose`, `keyframe`,
`clear_pose`, `retarget`, `set_action`, `rename_action`, `delete_action`,
`nla_push`, `nla_edit`, `nla_remove`, `constraint`, `remove_constraint`, `assign_weights`, `transfer_weights`, `bake`, `contact_lock`.

| Parameter | Used by |
| --- | --- |
| `name` | New armature, armature or skinned mesh |
| `location` | `create` |
| `bones` | `create`; 1–128 bone specifications |
| `names` | `bind`; 1–16 mesh names |
| `max_influences`, `clean_threshold`, `normalize` | `weights` |
| `poses` | `pose`; 1–128 poses |
| `keyframes`, `action_name` | `keyframe`; 1–32 frames |
| `frame` | `pose`, `clear_pose` |
| `reset` | `pose` |
| `source`, `source_action` | `retarget`; source armature and action |
| `mapping` | `retarget`; optional source-to-target bone map |
| `samples` | `retarget`; optional 2–256 samples |
| `calibration` | `retarget`; root, root translation scale and XYZ armature alignment |
| `new_name` | `rename_action`; new action name |
| `track_name`, `strip_name` | `nla_push`, `nla_edit`, `nla_remove` |
| `animation_target` | `set_action`, `nla_push`, `nla_edit`, `nla_remove`; `OBJECT` (default) uses an armature, `SHAPE_KEYS` uses the named mesh's Key datablock |
| `start_frame` | `nla_push`; default 1 |
| `strip_settings` | Optional for `nla_push`, required for `nla_edit`; sparse trim, scale, repeat, fade, blend, influence, mute and reverse settings |
| `source`, `new_name`, `max_distance_m`, `max_discarded_weight` | `transfer_weights`; required source skin, new copy and quality budgets |
| `shape_names` | `transfer_weights`; optional selected relative donor morphs, driven by donor value and mute |
| `max_influences` | `transfer_weights`; strongest influences retained and normalized, default 4 |
| `start_frame`, `end_frame`, `frame_step` | `bake`; positive fractional steps supported, at most 4096 samples |
| `new_name`, `action_name`, `names` | `bake`; independent rig/action and optional skinned copies |

[Guide](../guides/rigging-and-animation.md)

## render_preview

Lease-free. Returns a PNG MCP image.

| Parameter | Values |
| --- | --- |
| `path` | New workspace `.png` |
| `resolution` | 64–2048, default 512 |
| `names` | Optional 1–1000 meshes to isolate |
| `direction` | Camera direction from center |
| `color_mode` | `material` or `vertex` |
| `renderer` | `workbench` or `eevee` |
| `orthographic` | Boolean |

Eevee requires material colors and at most 1024 pixels.

## session_control

Lease-free. Inspects, claims, renews, releases or breaks edit ownership.

| Parameter | Values |
| --- | --- |
| `action` | `inspect`, `claim`, `renew`, `release`, `break` |
| `owner` | Claim label, at most 128 characters |
| `expected_project` | Exact `project_id` from inspect, for claim and break |
| `lease_id` | Claim token for renew and release |
| `ttl_seconds` | 30–3600, default 600 |

[Guide](../guides/session-ownership.md)

## object_edit

`make_single_user` copies shared mesh data on one editable object, including
shape keys, while retaining scene identity, transforms and material bindings.
It takes only `name` and `lease_id`; `mesh_copy` reports whether a copy was needed.

Mutating. Actions: `create_primitive`, `create_mesh`, `transform`, `set_color`,
`shade`, `apply_transforms`, `set_origin`, `snap_to_grid`, `rename`,
`add_socket`, `duplicate`, `make_unique`, `make_single_user`, `parent`, `unparent`, `move_to_collection`,
`shape_key_add`, `shape_key_value`, `shape_key_keyframe`, `shape_key_remove`.

[Guide](../guides/object-editing.md)

## mesh_edit

Mutating. Actions: `modifier`, `unwrap`, `decimate_to`, `remesh_quad`,
`lod_chain`, `lightmap_uv`, `texel_density`, `collision`, `cleanup`, `boolean`,
`join`, `separate`, `mirror`, `array`, `solidify`, `uv_transform`.

`uv_transform` takes a `uv_transform` object with required source `faces` and
optional `offset`, `scale`, `rotation_degrees`, `pivot`. `uv_layer` selects an
existing layer (default UV0). It preserves topology, skin and shape keys and
reports affected faces, materials and UV bounds. No implicit chart expansion.

[Guide](../guides/mesh-preparation.md)

## assign_material

`make_unique` copies the selected slots' authored material and nested node groups
to a new `material_name`. It takes `names`, `slot` (default 0) and `link_mode`
(default OBJECT). Image, action and scene references remain shared. Results include
`material_copy` and actual `bindings`.

Mutating. Binds a PBR material to exact mesh slots.

| Parameter | Values |
| --- | --- |
| `names` | 1–32 unique mesh names |
| `material_name` | 1–63 UTF-8 bytes |
| `base_color_texture`, `base_color` | sRGB map or RGBA scalar |
| `normal_texture`, `normal_strength` | Non-Color map; strength 0–10 |
| `roughness_texture`, `roughness` | Non-Color map; 0–1 |
| `metallic_texture`, `metallic` | Non-Color map; 0–1 |
| `emission_texture`, `emission_strength` | sRGB map; strength 0–1000 |
| `alpha_texture`, `alpha_mode` | Non-Color map; opaque, clip or blend |
| `uv_scale`, `uv_offset`, `uv_rotation_degrees` | One Mapping node |
| `update_existing` | Boolean |
| `slot` | 0–31, default 0 |

[Guide](../guides/materials-and-uvs.md)

## bake

Mutating. Bakes a normal, AO, curvature or lightmap map into a new PNG.
`bit_depth` accepts 8 or 16 and defaults to 16. Returns actual precision,
color-space role and canonical normal channels; requires an updated bridge.
Data maps bypass artistic view transforms; lightmaps use the sRGB transfer.

[Guide](../guides/baking.md)

## asset_io

Actions: `import`, `export`, `save`, `generate`. Import, export and save require
a lease. Export supports animated FBX, GLB and USD output and FBX and USD
texture sidecars with `textures=true`.

[Guide](../guides/asset-import-export.md) and
[local generation](../guides/local-generation.md).

## review_sheet

Lease-free. Returns one PNG contact sheet.

[Guide](../guides/previews-and-review.md)

## level_edit

Mutating. Actions: `terrain`, `place`, `snap`.

| Parameter | Used by |
| --- | --- |
| `name` | `terrain`; new object name |
| `image` | `terrain`; workspace PNG/JPEG heightmap |
| `size`, `height`, `resolution`, `location` | `terrain`; defaults `[100, 100]`, 10, 128, origin |
| `seed`, `octaves`, `frequency` | `terrain`; procedural noise, defaults 0, 4, 4 |
| `placements` | `place`; 1–256 `{source, name, location, rotation_degrees, scale, linked}` |
| `collection` | `place`; optional target collection |
| `names`, `terrain` | `snap`; 1–256 objects and the terrain mesh |
| `offset`, `align_to_normal` | `snap`; defaults 0 and false |

[Guide](../guides/level-assembly.md)

## scatter

Mutating. Adds a fixed Geometry Nodes scatter modifier.

[Guide](../guides/scatter.md)

## Response fields and failures

scene_info, inspect_mesh_quality, session_control and asset_io publish declared
response fields. Quality reports identify pixels_per_meter density units and
scene_unit_meters scale. Existing additional fields remain available.

Anticipated failures keep readable text and add an error object with version, code,
operation, outcome, retry_safe and next_action. INVALID_ARGUMENT and INPUT_NOT_FOUND
identify local validation/input failures. Transport or protocol uncertainty uses
OUTCOME_UNKNOWN and requires application/output inspection. retry_safe=false never
authorizes an automatic mutation retry. Unexpected defects remain opaque.


## scene_edit

Authors persistent scene definitions under an edit lease. Supply exactly the
model matching `action`: `camera`, `light`, `world` or `render`.

- `camera`: named camera, location/target, perspective or orthographic projection,
  focal length, sensor width, clip range, lens shift, depth of field, focus distance
  and f-stop. Existing camera names update in place; shared camera data is copied.
- `light`: named area, point, sun or spot light, location/target, energy, RGB color,
  area shape/size, radius, sun angle or spot cone/blend. Existing lights update in place.
- `world`: new managed color/HDRI node graph, strength and rotation. Workspace EXR,
  HDR, PNG, TIFF or JPEG inputs are hashed and packed into the editable project.
  Subsequent calls update that managed graph; an unrelated authored graph is preserved.
- `render`: renders the actual scene through the exact named camera, using Cycles
  or Eevee. The definition includes independent width/height, sample count, film
  transparency, color management, precision, thread count and pixel budget. Settings
  persist with the project. `scene_info(name=...)` reads camera/light definitions.

Production PNG/TIFF default to 16-bit; EXR supports half or full float through
`bit_depth="16"` or `"32"`. Explicit 8-bit PNG/TIFF remain available. Output paths
must be new workspace files. `max_pixels` defaults to 16777216 and may be raised
explicitly for larger images. `cycles_time_limit` limits Cycles sampling; it is
not a wall-clock deadline for scene preparation or Eevee. The result reports elapsed
seconds and whether Cycles may have reached its sampling limit. Requested sample
count is not a claim about samples achieved when a time limit intervenes.

Cycles defaults to CPU. `device="GPU"` uses the app's configured enabled Cycles
devices and refuses an unavailable GPU instead of silently falling back. Eevee uses
its native GPU renderer. Existing `render_preview` remains a separate temporary
preview operation with its original budgets.


Texture sidecars preserve loaded high precision images at PNG16. Color samples
are encoded once through sRGB; data-map samples use Raw. PNG sidecars require
finite normalized samples; remap signed/HDR values explicitly. Source images and
scene render profiles remain unchanged.

Animated `asset_io` exports accept `baked_animation: true` for a constraint- and
driver-free baked copy. GLB retains authored subframe keys; FBX exports the active
take rather than unrelated actions. FBX's optional `animation_sample_step` is a
positive frame interval within Blender's exporter bounds and disables key
simplification. Imported `source_objects` metadata maps exported identities to
actual import names; filter it to reported armatures and skinned meshes. Native
FBX import can shift clip start times, so inspect the actual active action range
before comparison. Shape-key channels may occupy a separate Action datablock.

`inspect_rig` also accepts declared `contacts` for bone-marker drift and world-Z ground-height checks. See [calibrated retargeting and contact windows](../guides/rigging-and-animation.md#calibrate-differing-rest-poses-and-proportions).

For baked or imported rigs, `contact_reference` names the source armature/action
and `contact_frame_scale`/`contact_frame_offset` align candidate clip time. See
[delivered contact checks](../guides/rigging-and-animation.md#check-contacts-after-bake-and-reimport).

`rig_edit bake` accepts optional `timing` (`start_frame`, `playback_rate`).
`compare_rig_motion` accepts `candidate_frame_scale` with its existing offset.
See [clip timing](../guides/rigging-and-animation.md#trim-rebase-and-retime-a-clip).

Baked FBX exports report their integer `animation_frame_range`. FBX imports clear
inferred connected-bone flags while preserving hierarchy and rest positions, so
joint translation keys remain effective.

`rig_edit contact_lock` takes `source_action`, `new_name`, `action_name`, optional `names`/`frame_step`, and typed `foot_locks`. See [editable contact correction](../guides/rigging-and-animation.md#correct-declared-foot-contacts).

## Source UV coverage

`inspect_uv_layout` with `udim_image` checks source UV triangles against an actual
tiled image. Use the exact `material` and `uv_layer` when needed. Its
`source_uv_udim_coverage` result requires `complete` and `coverage.passed`; it
reports missing/unavailable tiles and affected faces without claiming shader
vector evaluation. Omit texture resolution and padding in this mode. See
[source UV coverage](../guides/materials-and-uvs.md#check-source-uv-coverage).
