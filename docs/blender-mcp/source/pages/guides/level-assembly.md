# Build a level

`level_edit` creates terrain and assembles objects in the scene. Every action
requires a `lease_id`.

## Actions

| Action | Parameters |
| --- | --- |
| `terrain` | `name`; `image` or `seed`, `octaves`, `frequency`; `size`, `height`, `resolution`, `location` |
| `place` | `placements`; optional `collection` |
| `snap` | `names`, `terrain`; optional `offset`, `align_to_normal` |

## Terrain

`terrain` builds a regular grid with one UV layer and smooth shading. Without
`image`, deterministic value noise drives the height. With `image`, luminance
from a workspace PNG or JPEG heightmap drives it; black is 0 and white is
`height`. Image input overrides noise parameters.

`size` is the X and Y extent in metres, `height` is the elevation range and
`resolution` is the number of vertices per side. The terrain is centered on its
origin and placed at `location`.

## Placement

`place` copies mesh sources to absolute transforms. `linked=true` shares mesh
data; the default copies it. `collection` is created when missing. All names
must be new and unique. Scale components are positive.

## Snapping

`snap` casts a vertical ray from each object onto the terrain and places the
origin at the hit plus `offset`. `align_to_normal=true` tilts local Z to the
surface normal while preserving yaw.

## Related

- [Scatter instances](scatter.md)
- [Edit objects](object-editing.md)
- [Limits and boundaries](../reference/limits.md)
