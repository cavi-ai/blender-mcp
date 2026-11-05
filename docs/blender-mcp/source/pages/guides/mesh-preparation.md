# Prepare meshes

`mesh_edit` changes one exact mesh in Object Mode with single-user mesh data.
Every call needs a `lease_id`. Topology-changing actions require their own
modifier and shape-key preflight; `uv_transform` edits existing UV loops and
retains modifiers, skin weights and shape keys.

## Surface actions

| Action | Use |
| --- | --- |
| `modifier` | Add bevel, decimate, subdivision or voxel remesh; `apply` bakes it |
| `unwrap` | Smart UV Project and island packing |
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

## UVs

`unwrap` uses Smart UV Project then packing. `lightmap_uv` creates
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

## Composition

Booleans, joins, splits, mirrors, arrays and solidify restore the original scene
on failure. `join` takes 1–64 sources; `separate` creates 1–64 parts; `array`
allows 2–1000 copies.

## Related

- [Inspect a scene](scene-inspection.md)
- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
