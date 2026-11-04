# Tools

The server publishes 16 tools. Every mutation requires a `lease_id` unless the
tool is listed as lease-free.

Lease-free tools: `scene_info`, `inspect_mesh_quality`, `inspect_uv_layout`, `inspect_rig`,
`render_preview`, `review_sheet` and `session_control`. `asset_io` generation
also runs without a lease, but import, export and save do not.

## scene_info

Read-only. Returns Blender version, file, workspace, collection tree and a page
of objects. Mesh objects report `shape_keys`, `shape_key_names` and the
active `shape_key_action`.

Scene inventory responses include `bridge.protocol` and `bridge.build`, identifying
the implementation loaded inside Blender. `runtime status` compares this identity
with the installed server and exits nonzero on a mismatch. Preserve the project
and edit ownership before refreshing an outdated bridge.

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
set**, including overlaps between objects. Call separately for independent sets;
material slots do not automatically partition the report.

| Parameter | Values |
| --- | --- |
| `names` | 1–32 unique Object Mode mesh names |
| `texture_resolution` | Required width and height, each 1–16384 |
| `padding_pixels` | Required minimum chart separation and tile-border clearance, 0–256 pixels |
| `uv_layer` | Optional exact name; default is layer **index 0** |
| `comparison_budget` | 1–1000000 candidate comparisons; default 100000 |

Up to 20000 source triangles and 200000 source vertices per call, with at most
60000 loops per mesh. Modifiers and shape keys are not evaluated; this works on
raw static or skinned source UVs. Object ranges and selected UV layer indices
identify every reported triangle. Selection, geometry, UVs and edit ownership
are unchanged.

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

## rig_edit

Mutating. Actions: `create`, `bind`, `weights`, `pose`, `keyframe`,
`clear_pose`, `retarget`, `set_action`, `rename_action`, `delete_action`,
`nla_push`, `nla_remove`, `constraint`, `remove_constraint`, `assign_weights`, `bake`.

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
| `new_name` | `rename_action`; new action name |
| `track_name`, `strip_name` | `nla_push`, `nla_remove` |
| `start_frame` | `nla_push`; default 1 |

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

Lease-free. Inspects, claims, renews or releases edit ownership.

| Parameter | Values |
| --- | --- |
| `action` | `inspect`, `claim`, `renew`, `release` |
| `owner` | Claim label, at most 128 characters |
| `expected_project` | Exact `project_id` from inspect |
| `lease_id` | Claim token for renew and release |
| `ttl_seconds` | 30–3600, default 600 |

[Guide](../guides/session-ownership.md)

## object_edit

Mutating. Actions: `create_primitive`, `create_mesh`, `transform`, `set_color`,
`shade`, `apply_transforms`, `set_origin`, `snap_to_grid`, `rename`,
`add_socket`, `duplicate`, `parent`, `unparent`, `move_to_collection`,
`shape_key_add`, `shape_key_value`, `shape_key_keyframe`, `shape_key_remove`.

[Guide](../guides/object-editing.md)

## mesh_edit

Mutating. Actions: `modifier`, `unwrap`, `decimate_to`, `remesh_quad`,
`lod_chain`, `lightmap_uv`, `texel_density`, `collision`, `cleanup`, `boolean`,
`join`, `separate`, `mirror`, `array`, `solidify`.

[Guide](../guides/mesh-preparation.md)

## assign_material

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
