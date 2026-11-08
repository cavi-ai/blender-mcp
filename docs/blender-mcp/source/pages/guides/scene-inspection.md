# Inspect a scene

Inspection is read-only and needs no lease.

## Scene and objects

`scene_info` returns:

- `version`, `file` and `workspace`
- `total`, `offset`, `limit` and one page of `objects`
- the collection tree with per-collection object counts

Each object reports its type, transform, dimensions, parent, child count,
collections, modifiers and, for meshes, vertex and polygon counts, UV layer
count and material slots.

Use `name` to inspect one object without paging. Use `limit` (1–1000) and
`offset` to walk large scenes.

## Placement and surface clearance

Use `scene_info(spatial=["CanopyRoof", "Town"])` to inspect one named subject mesh
against one named context mesh at the current frame. The query evaluates modifiers and parent transforms
without moving objects or changing selection. It reports world bounds in metres,
geometry and query identities, triangle intersection pairs, and sampled nearest
surface points.

```json
{
  "spatial": ["CanopyRoof", "Town"]
}
```

The pair is ordered subject first, context second, and the names must differ.
The context may be a combined mesh containing several buildings or props.
This selector excludes pagination and all other `scene_info` inspection modes.

Bounds overlap is a broadphase result. `intersections` tests triangles through
native float32 BVHs plus a float64 projected separating-axis narrowphase for
coplanar triangles, including when a combined context mesh spans a large area.
The coplanar pass includes shared-edge/vertex contacts, uses a 0.000001-metre
plane/projected-edge tolerance and a 0.000001 normalized-normal cross-product
tolerance, and reports how many unique pairs it adds. It only examines overlapping
triangle bounds within the same pair-work budget. World coordinates outside finite
float32 range are rejected before native vector/BVH conversion.
`nearest` samples vertices and triangle centres in both directions and reports the
closest sampled witness. Its distance is an
upper bound on the continuous surface minimum. Neither zero intersection pairs nor
positive sampled gaps prove solid containment, physics clearance or absence of all
contacts. The report returns no all-clear verdict.

The fixed query budgets are 100,000 combined triangles, 500,000 combined vertices,
256 samples per side, 1,000,000 pair-work units and 32 intersection examples.
Spatial chunks contain at most
128 triangles, bounding each native overlap result to 16,384 pairs. Exceeding a
geometry or pair-work budget rejects the query; truncated examples retain the full
tested intersection count. Collection-instance empties, non-mesh geometry and
render-only modifier differences are outside this query's scope.

## Mesh quality

`inspect_mesh_quality` measures exact static mesh names. It refuses modifiers,
shape keys and rigs; bake a working copy first.

It always reports:

- physical texel density and directional UV stretch
- degenerate and missing mappings
- per-slot material bindings
- image metadata

Optional `checks` add:

- `naming`: lint against `mesh_prefix`, `lod_suffix` and
  `collision_prefixes`
- `topology`: non-manifold and boundary edges, loose vertices, zero-area faces
  and n-gons
- `lightmap`: presence and rasterized `overlap_ratio` of `lightmap_uv` at
  `lightmap_resolution`
- `transforms`: applied scale and rotation, delta transforms
- `origin`: position relative to local bounds
- `materials`: PBR map bindings, expected color spaces, packed image data,
  resolution consistency, unsupported graph state and UV transforms

Texture-UV overlaps, seam continuity and visual acceptance remain separate
checks.

## Rig inspection

`inspect_rig` reports bone hierarchy, linked actions and slots, and vertex-group
skin weights for one armature and 1–8 meshes.

Each mesh must have exactly one vertex-group Armature modifier bound to that rig.
The report includes unweighted, unnormalized, invalid and over-limit vertices
with bounded samples. `max_influences` selects the caller's target profile; it is
not a universal engine requirement.

Optional `action` selects a clip and `checks` adds animation QA. `root_motion`
reports displacement in armature space, `loop` compares first and last bone
matrices, and `deformation` reports evaluated mesh bounds, dimension ratios,
centroid movement and non-finite vertices. `samples` is 2–32 and defaults to 8.

It does not change pose, normalize weights or establish Unity import quality.
Foot sliding and engine import quality remain unchecked.

## Next

- [Edit objects](object-editing.md)
- [Prepare meshes](mesh-preparation.md)
- [Materials and UVs](materials-and-uvs.md)
