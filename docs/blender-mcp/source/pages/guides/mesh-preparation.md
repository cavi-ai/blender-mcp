# Prepare meshes

`mesh_edit` changes one exact mesh. It requires Object Mode, single-user mesh
data, no shape keys and, except for `modifier` without `apply`, no modifiers.
Every call needs a `lease_id`.

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

## Composition

Booleans, joins, splits, mirrors, arrays and solidify restore the original scene
on failure. `join` takes 1–64 sources; `separate` creates 1–64 parts; `array`
allows 2–1000 copies.

## Related

- [Inspect a scene](scene-inspection.md)
- [Materials and UVs](materials-and-uvs.md)
- [Limits and boundaries](../reference/limits.md)
