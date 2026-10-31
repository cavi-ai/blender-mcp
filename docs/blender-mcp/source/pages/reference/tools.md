# Tools

The server publishes 14 tools. Every mutation requires a `lease_id` unless the
tool is listed as lease-free.

Lease-free tools: `scene_info`, `inspect_mesh_quality`, `inspect_rig`,
`render_preview`, `review_sheet` and `session_control`. `asset_io` generation
also runs without a lease, but import, export and save do not.

## scene_info

Read-only. Returns Blender version, file, workspace, collection tree and a page
of objects. Mesh objects report `shape_keys`, `shape_key_names` and the
active `shape_key_action`.

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
`nla_push`, `nla_remove`.

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

[Guide](../guides/baking.md)

## asset_io

Actions: `import`, `export`, `save`, `generate`. Import, export and save require
a lease. Export supports FBX and USD texture sidecars with `textures=true`.

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
