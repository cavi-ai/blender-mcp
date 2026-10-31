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
