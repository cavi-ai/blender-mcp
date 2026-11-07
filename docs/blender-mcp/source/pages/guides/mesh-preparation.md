# Prepare meshes

`mesh_edit` changes one exact mesh in Object Mode with single-user mesh data.
Every call needs a `lease_id`. Topology-changing actions require their own
modifier and shape-key preflight; `uv_transform` and `unwrap_faces` edit UV loops and
retains modifiers, skin weights and shape keys.

For shared meshes, first use `object_edit` `make_single_user` to copy the data
on the same object without applying transforms or changing scene references.

## Surface actions

| Action | Use |
| --- | --- |
| `modifier` | Add bevel, decimate, subdivision or voxel remesh; `apply` bakes it |
| `extrude_faces` | Extrude exact source-face regions by a local-space vector |
| `unwrap` | Smart UV Project and island packing |
| `unwrap_faces` | Pack selected source faces into an explicit UV rectangle |
| `set_seams` | Set or clear exact source-edge seam flags without changing UVs |
| `move_vertices` | Translate declared source vertices and all their shape-key points |
| `decimate_to` | Collapse to a triangle target or ratio, optionally preserving seams |
| `remesh_quad` | QuadriFlow to a face target on a manifold mesh |
| `lod_chain` | Create `<base>_LOD1..n` in `<base>_LODs` |
| `lightmap_uv` | Create or repack a lightmap UV layer and report overlap |
| `texel_density` | Scale a UV layer to a target pixels-per-metre |
| `uv_transform` | Move, scale or rotate explicit source-face UV loops on an existing layer |
| `collision` | Create `UCX_`, `UBX_` or `USP_` collision objects per loose part |
| `cleanup` | Merge, delete loose geometry, recalculate normals, triangulate, clear custom normals |
| `boolean` | Union, difference or intersect against one operand |
| `join` | Consume sources into the target with transform, UV, group and slot remapping |
| `separate` | Split by loose parts or material |
| `extract_faces` | Copy explicit source polygons into an independent unrigged surface |
| `mirror` | Mirror across the object origin with optional clipping and merge |
| `array` | Constant object-space copies |
| `solidify` | Add thickness with an offset |

## LODs

`lod_chain` accepts `ratios` or `triangle_targets`, not both. Goals must strictly
decrease below LOD0. A source not ending in `_LOD0` is copied to `<base>_LOD0`
unless `rename_source=true`. The new collection must not already exist.

Each level reports `target`, `achieved`, `preservation`, `relaxed` and
`warnings`. Seam preservation relaxes from seams to unweighted seams to plain
decimation when it blocks a target. Results more than 10% over target stay in
`warnings`.

## Inspect and extrude a face region

Use `scene_info(name="Body", faces=true, offset=0, limit=100)` to page through
the source mesh's polygon indices, local centers, normals, areas and material
indices. Modifiers and deformation are not evaluated. Every page reports the
same `mesh_sha256` for unchanged local geometry and material indices.

```json
{"action":"extrude_faces","name":"Body","face_indices":[5,6],"offset":[0,0,0.2],"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

`offset` is in mesh-local coordinates. Adjacent faces extrude as one region;
separate regions remain independent. Object transforms stay unchanged. The
optional `expected_mesh_sha256` rejects a selection made from changed geometry.
It does not cover object transforms, UVs or shader graphs.

The edit validates a detached BMesh before replacing the source mesh. It
preserves existing UV layers, float color attributes, mesh properties and
object material overrides. Results identify the new `cap_faces`, `side_faces`
and resulting geometry hash. Use those new cap indices for another extrusion;
source face indices may change after any topology edit.

New side faces require UV layout and material review. Plan extrusion before
final unwrap and baking; existing cap/unselected UVs are retained. The tool does
not automatically pack the new surfaces or detect global self-intersections.
Run topology and UV checks, then inspect the silhouette before export.

Use `unwrap_faces` with the returned `side_faces` and geometry hash to lay out
the new surfaces while retaining the cap and unselected UVs.

## Adjust source vertices

Page `scene_info(name="Body", vertices=true, limit=100, offset=0)` for source
indices, local positions/normals and selection flags. Keep matching `mesh_sha256`
across pages. Vertex, face, edge and instance-definition modes are exclusive.

```json
{"action":"move_vertices","name":"Body","vertex_indices":[12,18],"offset":[0,0,0.025],"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

The operation translates the selected source points in local space. It requires
editable Object Mode data and independent mesh/shape-key data. Modifiers and
rigs remain attached. Every relative or absolute shape-key block receives the
same translation, retaining deformation offsets within native float storage.
The result's `vertex_edit` reports changed points, key-block count, geometry
hashes and measured `max_shape_delta_error_local`.

It preserves topology, UVs, pins, colors, weights, materials, rig and animation
links, and scene context. Selection accepts 1–20,000 unique source indices; at
most 1,000,000 mesh/key points are captured in one transaction. Validation runs
before assignment and native write/readback failures restore captured points.
Inspect texture stretch, normals, intersections and real poses after editing,
then save/reopen the source before export.

For proportional editing, pass `amount` as a positive radius in metres.
`vertex_indices` then selects full-weight seeds. Smoothstep falloff follows
shortest source-edge paths using object world scale and scene units. Nearby
disconnected surfaces stay untouched; UV seams and material boundaries do not
split the graph. Edge layout affects this source-space metric.

```json
{"action":"move_vertices","name":"Body","vertex_indices":[12],"offset":[0,0,0.025],"amount":0.05,"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

The receipt includes all affected indices plus `falloff` with seed indices,
radius, world metric and up to 64 weight samples (`weights_truncated` is explicit).
Each corresponding shape-key point receives the same weighted offset. Omitting
`amount` retains the declared-point translation. Proportional planning handles
up to 500,000 source vertices and 1,500,000 edges, with the existing affected-point
budgets. Excessive selections fail before assignment; no radius is silently reduced.

### Paired symmetry

Supply both `symmetry_axis` (`X`, `Y` or `Z`) and a positive
`symmetry_tolerance_m` to reflect displacement across the corresponding local
origin plane. The vector remains object-local. Matching compares reflected base
positions in world metres, including parent/object linear transforms and scene
units. It requires unique reciprocal matches; missing or ambiguous counterparts
reject the whole edit before writing.

```json
{"action":"move_vertices","name":"Body","vertex_indices":[12],"offset":[0.01,0,0.025],"amount":0.05,"symmetry_axis":"X","symmetry_tolerance_m":0.00001,"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

Seeds must occupy one side or the center band. Proportional paths remain on
that hemisphere, then mirror the weighted displacement. Center-only seeds use
the positive hemisphere. Center points (axis coordinate scaled into metres
within half the tolerance) receive only tangential displacement. This preserves
existing base asymmetry and each shape key's offsets; it does not symmetrize
expressions or weights. Inspect the origin and the actual left/right poses.

`vertex_edit.symmetry` reports the axis, tolerance, metric, source side, maximum
matching error and up to 64 source/partner pairs with explicit truncation.
Affected-point budgets include both sides. Matching is limited to 2,000,000
spatial candidate comparisons. Coincident split vertices are ambiguous;
disconnected geometry can be a valid mirrored counterpart. Omit both symmetry
arguments for the existing point/proportional workflows.

## Pick a mesh surface

Call `scene_info` with a mesh name and `surface_ray` containing `origin_world`,
`direction_world` and positive `max_distance_m`. Origins use scene world units;
direction is normalized and range uses metres. Optional `uv_layer` interpolates
the hit triangle's source corner UVs. This mode excludes pagination and the other
inspection modes.

```json
{"name":"Body","surface_ray":{"origin_world":[0,-2,1],"direction_world":[0,1,0],"max_distance_m":5,"evaluated":true},"uv_layer":"UVMap"}
```

`surface_pick.hit` distinguishes a hit from a successful miss. Hits report the
source polygon, triangle vertex/corner identities, barycentric weights, local
and world position, inverse-transpose world normal, metre distance and optional
UV position/hash. The query is two-sided and targets only the named mesh;
other objects are not occluders. Shared-edge ties can select either triangle.

The default uses base source coordinates. `evaluated=true` uses current posed
geometry with a deform-only stack and verifies indexed source topology before
returning source IDs. Unsupported or topology-changing stacks reject before
evaluation; they need a separate source mapping. The existing 500,000
vertex/triangle budget applies, plus a 1,500,000 evaluated-loop cap.

The receipt includes base/surface hashes, frame/subframe, scene units and world
matrix. BVH intersections retain native float32 precision. Evaluated hit positions
are deformed coordinates; inspect the returned source vertices before choosing
an edit. A base hash does not lock external pose or transform state. Re-pick after
those changes. Picking does not move the scene, selection or frame.

### Pick a camera pixel

Alternatively, `surface_ray` accepts `camera`, `pixel`, `image_size` and
`max_distance_m`, with optional `evaluated` and `expected_projection_sha256`:

```json
{"name":"Body","surface_ray":{"camera":"Hero","pixel":[320,240],"image_size":[640,480],"max_distance_m":5,"evaluated":true,"expected_projection_sha256":"<render-projection-sha256>"},"uv_layer":"UVMap"}
```

Pixels use zero-based top-left indices at their centers; fractional indices are
allowed. Image dimensions must match the current effective render raster.
Blender's projection matrix handles pixel aspect, lens shift and camera sensor
fit for perspective/orthographic views. The evaluated camera uses the renderer's normalized
transform. Rays start at the near plane; the far plane and
the requested metre range both limit hits. The receipt retains the projection
snapshot and effective world ray.

Named `scene_edit` renders return an image `sha256` and `camera_projection`.
An available projection is checked before and after rendering; a changed or
unsupported view receives `available=false` with a reason. Pass its hash when
picking to reject stale view state. This does not bind every scene-content edit
or compensate for depth of field, motion blur or compositor distortion. Use a
clean review pass and retain source identities. Border/cropped, stereo and
panoramic mappings are not inferred. Existing world-ray queries remain valid.

### Discover the scene target

Omit `name` with a camera query and `evaluated=true` to intersect the current view
layer's evaluated meshes and instances. The nearest hit returns the source object
name, material slot/name/link mode, generated placement matrix, instancer parent
and persistent instance ID. `hide_render`, camera-ray visibility and instancer
flags filter candidates. World-ray queries still require a named mesh.

The `scene_surface_pick` receipt explicitly distinguishes a hit from a miss.
`source_mapping.available` permits source face indices and source UVs only for
checked topology-preserving geometry. Generated topology remains discoverable,
with evaluated indices explicitly labeled; it cannot supply editable source
indices. A missing requested source UV map is reported unavailable.

This query uses current view-layer geometry, rather than executing a render.
Its `not_checked` fields cover shader opacity, non-mesh objects, render-only
visibility and render/viewport modifier differences. Keep these aligned for a
clean geometric selection pass. Transparent or coincident surfaces may need
separate inspection. Camera projection identities do not bind scene content.

World-space bounds discard objects away from the ray before detailed work.
Detailed candidates share a 500000-vertex/triangle evaluation budget per query;
an exceeded budget rejects the query instead of returning a partial nearest hit.
The query preserves selection, source geometry, camera, frame and materials.

### Bind picking to captured geometry

Named renders include `geometry_identity` beside `camera_projection` and the image
hash. An available identity fingerprints the current evaluated view-layer mesh
geometry, named UV layers and active UV state, object/instance placements and
material-slot bindings. The same candidate enumeration serves scene queries.
Canonical placement ordering retains duplicate instances; shared evaluated mesh
data is hashed once per snapshot.

Pass its `sha256` as `surface_ray.expected_geometry_sha256` with the projection
hash. A changed identity rejects picking before returning a target, including when
the camera is unchanged. The receipt records `geometry_identity_checked`; without
the optional expected hash it records false. Dirty flags, saved-file paths and
leases do not define geometric content. Exact geometric restoration can match an
earlier receipt.

Geometry is inspected before and after rendering. If it changes, the geometry
receipt is unavailable with a reason; the image remains usable. Unsupported or
over-budget identity capture is also reported unavailable. A snapshot supports up
to 500000 unique evaluated vertices/triangles and 1500000 edges/loops; instances
reuse their evaluated mesh data for this budget.

This is a geometric selection identity. Its `not_checked` list includes shader
parameters, image content, lighting, opacity, non-mesh geometry, render-only
visibility and render/viewport modifier differences. It does not establish
appearance equivalence or replace the image hash and source/pose identities.

## Assign source-face finishes

For distinct finishes on one connected mesh, inspect `scene_info(name=..., faces=true)`
and use `mesh_edit(action="assign_faces", name=..., material_name="TrimFinish",
face_indices=[...], expected_mesh_sha256=..., lease_id=lease)`. The material must
already exist. The operation reuses its first bound slot or appends one; it changes
only the selected source polygons' material indices. Shared mesh data requires an
explicit independent working copy. Rigged and shape-key meshes keep their surface,
UVs and deformation data. Inspect `face_material` for the actual slot, previous
indices and before/after source hashes, then save/reopen for persistent acceptance.

## Delete discarded objects


Inspect the current scene and save an owned source copy before deletion. Use
`object_edit(action="delete", name="Draft", lease_id=lease)` for one object.
An object with children requires explicit `recursive=true`, which includes its
parented descendants. A collection-instance placement can be removed without
deleting its shared definition.

The result returns `name`, sorted `deleted` names and their exact `count`.
Objects in other scenes, definitions used by surviving instances and external
content references are checked before any removal. A rejected hierarchy leaves
all its objects intact. Ambiguous object names are refused. Shared meshes and
materials remain; no datablock purge is performed.

Inspect the actual remaining scene and save/reopen when persistence is required.
A missing object is a rejection, not a no-op success. An uncertain native failure
requires inspection before another action; removal is not automatically retried.

## Inspect and edit seams

Page `scene_info(name="Body", edges=true, offset=0, limit=100)` to inspect
source edge indices, vertex endpoints, local center/length, seam flags and
adjacent face indices. Each edge includes `face_count` and `faces_truncated`;
adjacency lists contain at most 32 faces. Pages report both `mesh_sha256` and
`seams_sha256`. Match both across pages used for one selection. Edge, face and
collection-definition page modes are mutually exclusive.
Source topology pages handle up to 200,000 vertices/triangles and 600,000 edges.

```json
{"action":"set_seams","name":"Body","edge_indices":[4,9,12],"seam":true,"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

The seam state is required: `true` marks only those edges, `false` clears them.
The edit reports changed edge count and before/after seam hashes. It preserves
other seams, UVs, geometry, shape keys, weights, materials and scene context.
It requires a single-user editable mesh in Object Mode and accepts at most
20,000 unique current edge indices. Invalid indices and stale geometry hashes
are rejected before editing; partial writes are rolled back. The geometry hash
does not include seam flags. Reinspect after topology changes.

Use a single-user base mesh in Object Mode without modifiers or shape keys.
Custom split normals must be cleared deliberately on a working copy before
changing topology. Invalid indices, stale hashes, zero/degenerate offsets and
regions without a boundary are rejected before changing the object.

## UVs

### Identify complete source charts

Add an existing `uv_layer` to a source-face page:

```json
{"name":"Body","faces":true,"uv_layer":"BakeAtlas","limit":100,"offset":0}
```

The `uv` metadata reports the layer, chart count and `sha256` for its native
coordinates and pins. Each face adds `uv.chart`, `uv.chart_faces`, UV bounds and
pinned-loop count. A chart ID is its smallest source polygon index. Page the
whole source and group matching IDs to select every face in a chart; compare
both `mesh_sha256` and `uv.sha256` across pages before combining them.
The hashes detect mixed inspection state; they do not lock subsequent UV edits.

Connectivity follows shared source edges whose loop UV coordinates match exactly.
Disconnected stacked surfaces remain separate. Material boundaries and seam flags
do not split continuous coordinates. Membership includes finite degenerate charts;
it does not prove UV quality. This opt-in analysis handles 20,000 source triangles
and 60,000 loops, requires finite coordinates, and never evaluates modifiers.
Ordinary face pages without `uv_layer` keep their existing behavior.

`inspect_uv_layout` adds exact object, polygon and source-triangle identities to
each overlap/gutter example's `sources`. These identities refer to the original
mesh even after material filtering; objects report corresponding mesh/UV hashes.
The existing bounded examples and completeness flag still apply. Use whole-chart
membership when choosing the correction, then re-inspect the intended texture set.

### Unwrap selected faces

`unwrap_faces` takes current `face_indices`, an existing `uv_layer` (default UV0),
and a required `uv_region` with explicit bounds, texture width/height and pixel
padding. For example, reserve a clear rectangle for new side faces:

```json
{"action":"unwrap_faces","name":"Body","face_indices":[7,8,9,10],"uv_layer":"BakeAtlas","uv_region":{"bounds":[0.55,0.55,0.98,0.98],"texture_resolution":[2048,1024],"margin_px":8},"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

The native solver runs in a private background Blender process with selected
base geometry, accounting for object scale, rotation and scene units. It uses
Smart UV Project (`unwrap_method="smart"`, `angle_limit_degrees` default 66), packs islands, and scales
uniformly in pixels. Rectangular textures keep their pixel aspect. Bounds can
target an explicit UDIM region; they do not imply tile creation or material setup.

For seam-directed charts, select `unwrap_method="conformal"`, `"angle_based"`
or `"minimum_stretch"` and omit `angle_limit_degrees`. The worker receives the
seams of the selected source faces and preserves their cuts while solving the
surface. Selection boundaries also bound the working surface. The result
reports the exact method, `source_seams_sha256` and selected seam count. Native
failure never falls back to Smart UV Project. The source seam state is checked
again before UV writeback. Unwrap does not change the source seam flags.

By default, unselected UV triangles must leave the entire rectangle clear.
Selected pinned UVs are refused. Set `uv_region.allow_overlap=true` only for
deliberate reuse of an occupied region, and `allow_pinned=true` only when the
selected pinned coordinates should move. Pin flags remain intact. These overrides
do not disable overlap or gutter checks among the new islands. Padding applies
between islands and at the region border; choose it for the final resolution
and mip usage. Density matching with the retained layout requires a separate check.

Only selected corner coordinates in the chosen layer are written. Other layers,
unselected UVs, colors, materials, transforms, selection, geometry, skin weights
and shape keys stay intact. The source hash and all UV coordinates are checked
again before writeback. The result reports analytic overlap, degeneracy and
pixel-padding measurements on Blender's stored float precision. Partial writes
are rolled back. Inspect the actual material before accepting the layout.

The action requires a single-user editable mesh in Object Mode. It handles at
most 60,000 selected loops and 20,000 selected triangles, with 200,000 source
vertices/triangles. The worker has a 45-second limit and removes its scratch data.
It does not evaluate modifiers or deformations; use the intended rest or baked
working surface. It does not save a project, bake textures or change seams.

### Whole-layer preparation and placement

`unwrap` uses Smart UV Project then packing with `margin_px` (default 4) between
islands at `texture_resolution` (default 1024); `island_margin` instead sets the
margin as a fraction of the UV square. Faces that fold over their own island are
projected again at half the angle limit; any still folded become islands of their
own. Packing that produces zero-area, nonfinite or out-of-tile UVs is rejected and
the previous UV coordinates, pins, selection and layer flags are restored. Large
fractional margins can be infeasible on surfaces with many islands; the tool does
not reduce them automatically. Use `inspect_uv_layout` to check overlaps and the
required pixel gutters after a successful unwrap.
`decimate_to` dissolves faces collapsed onto coincident vertices. `lightmap_uv` creates
`UVMap_Lightmap` when missing, keeps the render-active layer and rasterizes the
overlap ratio. `texel_density` scales the layer around its UV bounds center;
`pack=true` rearranges islands without rescaling.

Use `uv_transform` to correct selected faces without re-unwrapping the asset:

```json
{"action":"uv_transform","name":"Body","uv_layer":"UVMap","uv_transform":{"faces":[12,13],"offset":[1,0],"scale":[1,1],"rotation_degrees":0,"pivot":[0,0]},"lease_id":"<claim-token>"}
```

Face indices refer to current source polygons, including indices reported by
`inspect_uv_layout`. Choose every face in a chart to move the whole chart;
selecting part of one intentionally splits its UV boundary. No island expansion
or packing is implicit. The existing named layer is used, or UV0 when omitted,
regardless of the active/render-active layer. Scaling precedes rotation about
the pivot; offset is applied last. Positive angles are counterclockwise.

The edit retains unselected UVs, other layers, selection, seams, materials and
native mesh data. Results report affected faces, loop count, materials and
before/after bounds. Invalid faces, duplicate indices, unavailable layers and
shared meshes are rejected before writing. Partial writes are rolled back.
Calls accept 1–20,000 faces and at most 60,000 selected loops; components and
resulting UVs must be finite within ±1,000,000, with rotation within ±360,000°.
Reinspect coverage and render the actual material before accepting a repair.

### Match a selected surface's density

Use `uv_transform` with both `target_px_per_m` and `uv_region` to compute a
uniform scale for the declared source faces. The destination supplies final
texture width/height, reserved bounds and pixel gutters; dimensions can be
rectangular and reach 16,384 pixels. Choose the target from the asset's texture
budget or a measured neighboring surface.
Density matching shares the source and selected-triangle budgets of `unwrap_faces`.

```json
{"action":"uv_transform","name":"Body","uv_layer":"BakeAtlas","uv_transform":{"faces":[12,13],"pivot":[0.75,0.75]},"target_px_per_m":512,"uv_region":{"bounds":[0.5,0.5,1,1],"texture_resolution":[2048,1024],"margin_px":8},"expected_mesh_sha256":"<inspected-mesh-sha256>","lease_id":"<claim-token>"}
```

These numbers are an example. Keep explicit `scale` at `[1,1]`; the target
computes its own factor. Pivot, offset and rotation retain their UV-space
meaning. The operation uses unevaluated source positions with object world
scale and scene units, retaining rig, weights, shape keys and other mesh data.
An optional `expected_mesh_sha256` also guards ordinary UV transforms.

The existing region policy protects selected pinned coordinates and requires
clear space around the selected charts. Explicit `allow_pinned` and
`allow_overlap` have the same meanings as for `unwrap_faces`. The correction
does not repack islands, lower the density target, or resample texture images.
It checks overlap, degenerate UVs, region borders and inter-island gutters on
the coordinates to be stored, then verifies native readback. A failed write
or readback check restores the original selected UVs.

`uv_transform.density` reports before/after area-weighted RMS pixels per metre,
minimum/maximum density and directional anisotropy. Stored coordinates must
meet the requested aggregate within 0.01 percent. Uniform scaling retains
existing stretch; additional UV rotation on rectangular textures can change
it. Inspect the reported anisotropy and actual material. Source UV density
excludes shader mapping transforms and posed deformation. Apply corrections
before final painting/baking, then validate the resulting texture placement.

## Composition

Booleans, joins, splits, mirrors, arrays and solidify restore the original scene
on failure. `join` takes 1–64 sources; `separate` creates 1–64 parts; `array`
allows 2–1000 copies.

`extract_faces` takes `new_name` and 1–20,000 unique `face_indices` from the
current source polygons. The new object keeps the source world transform,
material slots, selected corner UVs and native mesh attributes; the original
mesh is unchanged. It removes unused geometry without filling boundaries or
inferring garment regions. The source must have no modifiers, shape keys,
vertex groups or armature binding. Every index and the new name are checked
before copying; sheared or singular world transforms are refused. Failure
removes only the new output. The raw subset is an open, unrigged patch: garment
thickness, fit, rigging, facial animation and deformation require separate checks.

```json
{"action":"extract_faces","name":"Surface","new_name":"GarmentPatch","face_indices":[12,13],"lease_id":"<claim-token>"}
```

## Related

- [Inspect a scene](scene-inspection.md)
- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
