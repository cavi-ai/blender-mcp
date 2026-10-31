# Cavi Blender MCP

Typed MCP tools for Blender scene inspection, mesh editing, previews, and game asset export.

## Install

Requires Python 3.11+, uv, and Blender. Native import and runtime checks have been exercised with Blender 5.2.3 LTS. Dependencies are pinned in `uv.lock`.

```sh
uv sync --locked
```

Start a dedicated Blender session with the bridge. Use your Blender executable and the absolute path to this checkout:

```sh
blender --factory-startup --python /path/to/blender-mcp/scripts/start_bridge.py
```

`--factory-startup` opens a separate default scene without loading or saving user preferences. To use an existing project, explicitly open its working copy in this dedicated session. The bridge grants access to scene contents; use only trusted local MCP clients.

Register the stdio server in your MCP client:

```json
{"mcpServers":{"blender":{"command":"/path/to/blender-mcp/.venv/bin/cavi-blender-mcp"}}}
```

Call `scene_info` first. The bridge must be running inside Blender; the stdio MCP server does not launch an application or authenticate accounts. Use the explicit runtime CLI to start a dedicated Blender session when needed.

### Runtime commands

```sh
cavi-blender-mcp runtime start
cavi-blender-mcp runtime start --project working-copy.blend
cavi-blender-mcp runtime start --background
cavi-blender-mcp runtime status
cavi-blender-mcp runtime restart --lease-id <current-lease>
```

`start` reuses a connected session or launches Blender with factory settings, embedded
script auto-execution disabled, and the packaged bridge. It starts only when the prior
connection is missing or refused; timeouts and uncertain failures leave existing sessions
untouched. `--project` selects an existing workspace-relative `.blend` and refuses to
replace a different connected project. `CAVI_BLENDER_BIN` overrides executable discovery;
otherwise the CLI uses Blender on PATH or the standard macOS installation. The connection
file and workspace environment variables select the dedicated session. Launch acceptance
does not prove readiness; require a successful status check before asset operations.
`--background` launches headless Blender; the bridge blocks its main thread on the request queue
and removes its connection file on SIGTERM. The connection file records the Blender pid; a file
whose pid is no longer alive is treated as offline and removed.

`status` and `restart` control the bridge inside an already running Blender session. Restart replaces
its local listener and credentials, then checks the new connection. It preserves the Blender
process, open scene, unsaved edits, and selection. A failed request is never automatically retried.
Commands print JSON and exit nonzero on failure. `CAVI_BLENDER_CONNECTION` selects
the session to control. Sessions started with an older bridge need to be reopened with the
updated `start_bridge.py` once before these commands are available.

Runtime restart does not reload Python source or refresh an MCP client's cached tool catalog.
After installing new tools, restart that client's MCP connection to discover them. Running
`cavi-blender-mcp` without arguments continues to serve MCP over stdio.

## Tools

- `session_control`: `action` = inspect | claim | renew | release application edit ownership.
- `scene_info`: version, file, workspace, collections, and a page of objects (`limit` 1–1000, default 200; `offset`; returns `total`). Objects report parent, children, collections and dimensions. With `name`, returns that object's details.
- `inspect_mesh_quality`: read-only physical texel density, directional UV stretch, degenerate mappings, per-slot material bindings, and image metadata on exact static mesh names. Optional `checks`: `naming` (lint against `naming` = `mesh_prefix`, `lod_suffix` `_LOD{n}`, `collision_prefixes`), `topology` (non-manifold and boundary edges, loose vertices, zero-area faces, n-gons), `lightmap` (presence and rasterized `overlap_ratio` of `lightmap_uv` at `lightmap_resolution`), `transforms` (applied scale/rotation), `origin` (position relative to local bounds), `materials` (PBR map bindings, expected color spaces, packed image data, resolution consistency, unsupported graph state and UV transform). Texture-UV overlaps, seams, and visual acceptance remain separate checks; unbaked modifiers and rigs are refused.
- `inspect_rig`: read-only bone hierarchy, linked actions/slots and vertex-group skin weights for an exact `armature` and 1–8 `meshes`. Reports unweighted, unnormalized, invalid and over-limit vertices with bounded examples. `max_influences` (1–32, default 4) selects the target profile. Each skin must have one vertex-group Armature modifier bound to that rig. Limits: 512 bones, 100,000 total vertices/triangles, one million assignments. Does not change pose, normalize weights, validate animation deformation or establish Unity import quality.
- `rig_edit`: `action` = `create` (new armature from 1–128 `bones` = name, head, tail, parent, connect, deform, roll_degrees; `location`), `bind` (automatic weights from `name` armature to 1–16 `names` meshes; no modifiers or shape keys, at most 50,000 vertices and 64 bones), `weights` (`name` skinned mesh; `max_influences` 1–32, `clean_threshold`, `normalize`; bounded to 100,000 vertices and one million assignments), `pose` (`name` armature, `poses`, optional `frame`, `reset`), `keyframe` (`name` armature, new `action_name`, `keyframes` = 1–32 `{frame, poses}` entries; 1–128 poses each and 2,048 total; keyframes rotation/location/scale into a new action), `clear_pose` (`name` armature, optional `frame`). Binding and repair snapshot mesh data and restore it on failure; keyframe creation removes the new action and restores the previous action and pose on failure. Manual pose edits are not keyed, and an active action re-evaluates on frame changes. Use `inspect_rig` to verify the result.
- `render_preview`: render a PNG and return an MCP image; no lease needed. `names` isolates meshes (other renderable objects are hidden), `direction` picks the view, `orthographic` switches the camera. Workbench checks shape; `renderer="eevee"` checks materials under temporary studio lighting at up to 1024 pixels. Scene state is restored afterward.
- `object_edit`: `action` = `create_primitive` (`kind`, `location`), `create_mesh` (`vertices`, `faces`), `transform` (`location`, `rotation_degrees` XYZ Euler, honoring the object's rotation mode, `scale`), `set_color` (`rgba`, `slot`=0; reuses one color material per object slot), `shade` (`smooth`), `apply_transforms` (`components`=[rotation, scale]; shared mesh data needs `make_single_user`=true; children keep their world transforms), `set_origin` (`origin` = bounds_bottom_center | bounds_center | world_origin | point with world `location`; geometry stays in place), `snap_to_grid` (`grid`), `rename` (`new_name`; also renames single-user mesh data), `add_socket` (empty `SOCKET_<new_name>` parented at local `location`, `rotation_degrees`), `duplicate` (`new_name`; `count`, world `offset`, `linked`), `parent` (`new_name`; preserves world transform and refuses cycles), `unparent` (preserves world transform), `move_to_collection` (`new_name`, `create`).
- `mesh_edit`: `action` =
  - `modifier` (`kind` bevel | decimate | subdivision | voxel_remesh, `amount`, `apply`)
  - `unwrap` (Smart UV Project then pack; `angle_limit_degrees`=66, `island_margin`=0.02, optional `uv_layer`, created if missing)
  - `decimate_to` (`target_triangles` or ratio `amount`; collapse with `symmetry_axis`; `preserve`=[seams] weights UV seams, UV island borders and open boundaries; up to three passes; returns achieved `triangles`)
  - `remesh_quad` (QuadriFlow to `target_faces`; `preserve` sharp | boundary, default boundary; needs a manifold mesh; UV layers are not kept)
  - `lod_chain` (`ratios`=[0.5, 0.25, 0.125] or `triangle_targets`; creates `<base>_LOD1..n` with the same materials and UVs in collection `<base>_LODs`; a source not ending in `_LOD0` is copied to `<base>_LOD0` unless `rename_source`=true)
  - `lightmap_uv` (Smart UV Project and pack into `uv_layer`=UVMap_Lightmap with margin `margin_px`/`lightmap_resolution`; keeps the render-active layer; returns `overlap_ratio` rasterized at `lightmap_resolution`)
  - `texel_density` (uniformly scales the layer around its UV bounds center to `target_px_per_m` at `texture_resolution`, measured as in `inspect_mesh_quality`; `pack` rearranges islands without rescaling)
  - `collision` (`shape` convex | box | sphere → `UCX_`/`UBX_`/`USP_<base>_NN` per loose part, unparented, world transform of the source; convex hulls are capped at `max_hull_vertices` (≤255) by farthest-point sampling; `<base>` drops a `_LODn` suffix)
  - `cleanup` (`merge_distance`, `steps` from merge, delete_loose, recalc_normals, triangulate, clear_custom_normals; returns count deltas)
  - `boolean` (`operand`, `operation` union | difference | intersect; `solver` exact | fast, `keep_operand`, `self_intersection`; transfers materials; removes the operand unless `keep_operand`=true)
  - `join` (`names`; consumes the sources into `name`, remapping transforms, UVs, vertex groups and material slots)
  - `separate` (`by` loose_parts | materials; keeps the source as part 0 and creates `<name>_part_NN`)
  - `mirror` (`symmetry_axis`; `merge_distance`, `clipping`; mirrors across the object origin)
  - `array` (`count`, constant object-space `offset`)
  - `solidify` (`thickness`, `offset`)
- `assign_material`: bind a PBR material to exact mesh slots and pack bounded workspace PNG/JPEG maps: `base_color_texture`, `normal_texture`/`normal_strength`, `roughness_texture`, `metallic_texture`, `emission_texture`/`emission_strength`, and `alpha_texture`/`alpha_mode` (opaque | clip | blend). `uv_scale`, `uv_offset` and `uv_rotation_degrees` drive one Mapping node; base color and emission use sRGB, the remaining maps use Non-Color. `base_color`, `roughness` and `metallic` set scalar values when maps are absent. `update_existing` edits a material created by this tool that is bound to the slot, preserving unspecified settings and replacing supplied maps; untagged materials are refused and maps cannot be removed. Other slots are preserved; UVs and single-user mesh data are required for textured assignment. Each image is at most 16 MiB and 4096², with a combined 32-million-pixel budget.
- `asset_io`: `action` = `import` (GLB `path`, new `name`; static, skinned or animated), `export` (`names`, `.fbx`/`.glb`/`.usd`/`.usda`/`.usdc` `path`, `preserve_instances`, `include_empties`, `lods`, `collision`, `animations`, `axis`, or `bake_pair`), `save` (new `.blend` `path`), `generate` (`image`, `.glb` `path`, `resolution`; local TripoSR, no lease). `animations=true` applies to FBX and GLB only, includes the armatures of the named meshes, exports every linked action, and refuses LODs, collision, instances and pair baking.
- `review_sheet`: one PNG contact sheet of up to six `views` (front, back, left, right, top, persp) exactly `resolution` px wide (≤ 2048; tiles centered); `mode` = shaded | wireframe | uv_checker | texel_heatmap (blue below, green on, red above `target_px_per_m` at `texture_resolution`) | matcap. Read-only stand-ins; no lease.
- `scatter`: adds a fixed Geometry Nodes modifier that instances `collection` over the mesh surface: `density` per m², `seed`, `min_distance` (Poisson), `scale_range`, `rotation_jitter_degrees` about Z, `realize`. Bounded to 100,000 estimated instances and 2,000,000 realized triangles; no caller-authored node graphs.

### Engine exports

- `lods=true` adds every `<base>_LODn` sibling of each name so Unity builds a LODGroup.
- `collision=true` adds `UCX_`/`UBX_`/`USP_<base>_NN` objects.
- `bake_pair={"high": [...], "low": [...]}` writes `<stem>_low.fbx` and `<stem>_high.fbx`; objects and single-user meshes are temporarily named `<base>_low`/`<base>_high` for name-matched baking (Substance Designer), then restored. Each base needs exactly one low and one high object. Map baking is out of scope.
- `axis` (FBX and USD; default unity): unity = Y forward, Z up (FBX; Unity's `bakeAxisConversion` converts), FBX_SCALE_UNITS, no bake; USD -Z forward, Y up; unreal = X forward, Z up, FBX_SCALE_NONE, no bake; godot = -Z forward, Y up, FBX_SCALE_ALL, baked space transform. glTF is always +Y up.
- `animations=true` includes the armatures of the named skinned meshes and exports every linked action for FBX or GLB. It refuses LOD, collision, instance and pair-bake combinations.
- GLB export embeds packed PBR images. USD export writes selected meshes and materials without animation, lights, cameras or texture copies. FBX export does not copy or embed sidecar textures.

Static FBX exports use file unit metadata, Blender's native Z-up axes with identity node transforms (import in Unity with `bakeAxisConversion`), face smoothing and tangents. `include_empties` adds empty ancestors and empty descendants, such as sockets, of the named meshes. GLB exports apply modifiers. `preserve_instances=true` shares geometry between local, unmodified static FBX sources with matching distinct populated material slots; source mesh data and bindings are restored after export.

Every mutation except `render_preview`, `review_sheet` and `generate` requires a `lease_id`. Unrelated or missing per-action parameters are refused before contacting Blender.

Materials are Blender preview colors. Exported assets still need the destination game's materials, scale, collision and import settings.
Material, shading and UV edits refuse shared mesh data to avoid changing linked objects implicitly. Make the mesh single-user in Blender before editing it.

## File and connection boundaries

`CAVI_BLENDER_WORKSPACE` selects the output workspace, defaulting to `~/Documents/CaviBlender`. Save/export/preview paths must remain inside it, including through symbolic links. Existing files are refused. Parent directories must already exist.

The bridge binds only to `127.0.0.1` on an ephemeral port and requires a random session token. `CAVI_BLENDER_CONNECTION` selects its private connection file, defaulting to `~/.cavi/blender-mcp/connection.json`. Keep it out of repositories. Separate concurrent sessions require separate connection files configured in both Blender and the MCP server.

There is no arbitrary Python tool, telemetry or external asset download. Changes are not retried after a timeout; inspect the scene before resubmitting an uncertain mutation. Requests time out after 60 s (import, export, modifier, render, save and most geometry actions: 300 s; `remesh_quad` and `lod_chain`: 600 s, the cap). Bridge failures return JSON errors: 400 bad request, 413 too large, 503 queue full, 504 not started in time. Blender operations run on the main thread. The bridge stops when its Blender process exits.

Custom meshes accept 3–10,000 vertices, 1–20,000 faces and at most 100,000 face indices within the 8-MiB request limit. Faces use zero-based indices and outward winding. Invalid indices, repeated vertices and zero-area faces are refused before creating a Blender datablock. Disconnected shells are allowed for voxel fusion. Subdivision supports integer levels 1–3 within 500,000 estimated faces; remeshing requires a voxel size of 0.005–1 local units within a two-million-voxel bounding volume. Both organic modifiers require an object without existing modifiers to bound evaluation cost.

Bevel is bounded by the evaluated geometry; unapplied modifier stacks are limited to 16.

Geometry actions need Object Mode, single-user mesh data without modifiers or shape keys, and at most 500,000 triangles (`remesh_quad`, `collision`, `lightmap_uv`, `texel_density`: 200,000; `remesh_quad` targets 16–100,000 faces; `lod_chain` 1–6 levels; collision 1–64 loose parts). Reductions bake through the evaluated mesh rather than context operators; QuadriFlow and UV packing run through Blender operators, including in `runtime start --background`.

Composition also requires Object Mode, single-user meshes without modifiers or shape keys. Booleans bound the two inputs and result to 500,000 triangles; `fast` selects Blender's float solver, `exact` its exact solver. `join` takes 1–64 sources, `separate` creates 1–64 parts, `array` allows 2–1000 copies within the 500,000-triangle result budget, and `duplicate` creates 1–256 objects. Failed booleans, joins, splits, duplicates and modifier bakes restore the original scene.

Rigging requires Object Mode. Armatures accept 1–128 bones with unique names, non-zero lengths, acyclic parents, and connected bones that meet their parent tail. Automatic binding requires 1–16 single-user meshes without modifiers or shape keys, at most 50,000 vertices and 64 bones. Weight repair affects deform-bone groups only and is bounded to 100,000 vertices, 512 groups and one million assignments. Animation authoring is bounded to 32 frames per action, 128 poses per frame and 2,048 poses per call. Binding and repair restore mesh data, parents, transforms and modifiers on failure; action creation removes the new action and restores the previous action and pose on failure. Animated exports are bounded to 64 meshes, 100,000 vertices, 200,000 triangles, 128 bones per armature and 32 actions.

`decimate_to` and each `lod_chain` level report `target`, `achieved`, `preservation` (`seams`, `seams_unweighted`, `plain`) and `relaxed`. Seam preservation is relaxed in that order when it blocks a target; results still more than 10% over target are listed in `warnings`.

`mesh_edit` `modifier` defaults to a non-destructive modifier. Its optional `apply` flag bakes the result into a single-user mesh without an existing modifier stack, allowing fusion, smoothing and reduction in sequence.

## Local image-to-3D

Generation is optional and runs in a separate Python 3.11 environment. The MCP process does not import PyTorch, download weights or send images to a remote service. The worker uses [TripoSR](https://github.com/VAST-AI-Research/TripoSR), with CPU mesh extraction through scikit-image. Code and weights are MIT licensed. Its generated surfaces still require inspection, animation rigging and game import work.

After generation, call `asset_io` with `action="import"`, that workspace-relative GLB `path`
and a new asset `name`. Returned object names can be used with the editing and export tools.
Imports preserve transforms, UVs, and vertex colors; embedded images are packed into
Blender. A failed import removes its new datablocks and restores selection. The source
file is hashed, validated, and copied to a private snapshot before Blender reads it.

Import is limited to one-scene triangle GLBs of at most 64 MiB, 1,000 nodes,
500,000 vertices and triangles, and a combined 4096×4096 embedded-image pixels. PNG and JPEG
images may be embedded; external dependencies, cameras, lights, morph targets, compressed
geometry, and cyclic or excessively deep node hierarchies are refused. Skins are supported
with up to 16 skins, 512 joints each, 1,024 joints total, 64 skinned meshes and four
influences per vertex. Animation clips are supported with up to 32 clips, 1,024 total
channels and samplers, 100,000 keys per clip and 256,000 keys total, using translation,
rotation or scale targets with LINEAR, STEP or CUBICSPLINE interpolation. Imported armatures,
skinned meshes and actions work with `inspect_rig`, `rig_edit` weight repair and animated
exports. Import names accept at most 58 UTF-8 bytes to leave room for object suffixes.

Prepare a separate runtime with `uv venv --python 3.11 /path/to/neural-env` and `uv pip install --python /path/to/neural-env/bin/python -r requirements-neural.txt`. Check out upstream TripoSR at commit `107cefdc244c39106fa830359024f6a2f1c78871`. Download `config.yaml` and `model.ckpt` from the public `stabilityai/TripoSR` model at revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`, plus `facebook/dino-vitb16/config.json` saved as `dino-config.json` in the same weights directory.

Configure these absolute local paths in the MCP server environment:

```text
CAVI_TRIPOSR_PYTHON=/path/to/neural-env/bin/python
CAVI_TRIPOSR_SOURCE=/path/to/TripoSR
CAVI_TRIPOSR_WEIGHTS=/path/to/weights
```

Put an image of one isolated object on white or transparency inside the Blender workspace. Call `asset_io` with `action="generate"`, its relative `image` path and a new `.glb` output `path`. Generation runs offline on CPU with four threads, chunked field queries and a 180-second timeout. Resolution is bounded to 64–192; input images are at most 16 MiB and 4096 pixels per side. Outputs are published without replacing existing files. The returned counts and input SHA-256 identify the generated artifact. Generation creates a GLB file without changing the open scene.


## Shared application ownership

Before editing, call `session_control` with `action="inspect"`, then claim the
returned `project_id` with `action="claim"`, an `owner` label, and that exact
`expected_project`. Claim returns a private `lease_id`; pass it on application
mutations. Read-only inspection remains available without ownership.

Claims last 30–3600 seconds, default 600. Renew with `action="renew"` and release
with `action="release"`, both supplying the same `lease_id`. Release and expiry
never save, close, or discard a project. Conflicting claims and missing, foreign,
expired, or project-mismatched edit tokens are refused. An owned operation holds
its exclusive section until it finishes. A successful owned save or project
transition updates the claim's binding.

Claims coordinate participating MCP clients, not direct human edits or arbitrary
scripts. Upgrade every participating client. Keep lease IDs out of asset receipts
and handoff documents; a new agent inspects and claims its own session.

Blender also needs the upgraded bridge loaded. Preserve the scene before
reopening its dedicated application session. New MCP edits use an owned-edit
protocol envelope that older bridges reject. Listener restart does not reload
bridge code and requires the current edit lease.

## Validation

```sh
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py -- /path/to/empty/test-workspace
```

The native smoke creates a disposable scene, edits a mesh, unwraps UVs, exports FBX/GLB, saves a project, and renders a preview. It does not edit a game project.

The additional `tests/blender_organic.py` native check exercises custom topology, evaluated subdivision/remeshing, resource limits, preview isolation and a GLB export/import round trip. Invoke it with the same Blender command and a separate empty workspace.

`tests/blender_harden.py` checks rotation modes, color material reuse, named UV layers, modifier budgets, lease-free previews, FBX settings, and the bridge's request cap and error statuses.

`tests/blender_aaa.py` checks decimation, LOD chains, QuadriFlow, lightmap overlap, texel density, collision naming, cleanup deltas, transform/origin edits, sockets, inspection checks, LOD/collision/USD/bake-pair exports with FBX re-import, every review sheet mode and scatter budgets.

`tests/blender_compose.py` checks booleans and rollback, joins with transforms/materials, loose and material splits, mirror/array/solidify bounds, linked and copied duplicates, parent/unparent world transforms, collection moves, hierarchy reporting and ownership.

`tests/blender_rigging.py` checks armature creation, hierarchy validation, automatic binding, normalization/limit repair, rollback cases, ownership and bounded bone lists.

`tests/blender_animation.py` checks pose/reset, action creation and slot ranges, invalid keyframes, animated FBX/GLB export with armatures and skins, USD/unskinned/LOD refusals, and FBX/GLB re-import.

`tests/blender_pbr.py` checks PBR map color spaces, packing, normal/emission/alpha bindings, UV transforms, update-existing preservation, rollback after invalid updates, material QA findings and a GLB export/import round trip.

`tests/blender_golden.py` checks convex hulls of meshes with interior points, lightmap packing time, LOD/decimation relaxation and warnings, and exact review sheet width.

`tests/blender_headless.py` starts `runtime start --background` from an installed-package layout with a shadowing server `numpy` and runs a numpy-backed inspection; pass the venv Python after `--`.

`tests/blender_unity_axis.py` checks unity-axis FBX node transforms, socket export and upright re-import.

`tests/blender_import.py` checks typed import on Blender 5.2.3, including transforms,
UVs, vertex-color values, embedded image packing, name reuse, selection preservation,
and rollback after a partial native import. It uses a disposable factory scene and
temporary workspace; no game project is opened.

`tests/blender_rigged_import.py` checks skinned GLB import, armature and vertex-group
preservation, `inspect_rig` on the imported result, duplicate-name rejection, and rollback
after a partial import.

`tests/blender_animated_import.py` checks animated GLB import, imported action frame ranges,
`inspect_rig` clips, re-export to FBX/GLB, duplicate-name rejection and rollback.

## MCP evaluation

Install the locked Python and evaluator dependencies, then run the protocol checks:

```sh
uv sync --locked --dev
npm ci
npm run eval:protocol
npm run eval:core -- --blender /path/to/blender
```

The evaluator is pinned to `@cavi-ai/mcp-eval` 0.8.0. The protocol manifest checks discovery size, catalog token budgets, pagination, surface listing, and protocol negotiation. The core manifest adds schema, structured output, repeated reads, and contention checks. The corpus covers all 12 tools through real stdio MCP sessions, including PNG image data, nonempty exports, GLB imports, packed color materials, lit previews, geometry actions, rig creation/binding, rig inspection, review sheets, scatter, and edit ownership. The optional model case requires a configured runtime and `--model-image`; ordinary protocol/native runs report model evaluation as not run. No-argument read tools have no tool-specific invalid inputs.

To exercise actual image-to-3D inference, append `--model-image /path/to/original.png` to the native evaluator command. The resulting GLB and report are retained in that run's artifact directory.

Native evaluation starts its own factory scene with a private connection and disposable workspace. It does not connect to an existing Blender session. Reports and application logs remain under `.tmp/evals/`; connection files, scenes, and outputs are ignored by Git. An unavailable executable fails the command rather than producing a native pass. CI runs protocol checks; native checks require Blender and run separately.

These are deterministic protocol and native application evaluations. MCP Eval does not invoke a model; results do not establish model task quality or game integration.
