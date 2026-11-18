# Scatter instances

`scatter` adds a fixed Geometry Nodes modifier that instances a collection over
a mesh surface. It requires a `lease_id`.

The node graph is code-defined. Callers cannot supply arbitrary node trees.

## Inputs

| Parameter | Meaning |
| --- | --- |
| `name` | Target mesh |
| `collection` | Instance collection |
| `density` | Points per square metre, above 0 to 10,000 |
| `seed` | 0–1,000,000 |
| `min_distance` | Optional Poisson spacing, 0–1000 |
| `scale_range` | `[min, max]` within 0.01–100 |
| `rotation_jitter_degrees` | Z rotation range, 0–360 |
| `realize` | Convert instances to geometry |
| `align_to_normal` | Instance Z follows the face normal; jitter spins about that axis |
| `max_slope_degrees` | Skip faces steeper than this from world up, 0–90; needs uniform scale |
| `density_group` | Target vertex group whose weight scales density from 0 to 1 |

## Budgets

- The target must have 1–500,000 evaluated triangles and a nonzero world area.
- The collection must contain 1–256 objects including at least one mesh.
- The target cannot be inside its own instance collection.
- Estimated instances are capped at 100,000.
- Realized output is capped at 2,000,000 triangles.

The result reports the modifier, node group, collection, estimated and evaluated
instance counts, evaluated triangles when realized, the seed, and the alignment,
slope and density group settings.

## Related

- [Prepare meshes](mesh-preparation.md)
- [Limits and boundaries](../reference/limits.md)
