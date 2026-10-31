# Limits and boundaries

Every input and output is bounded. Requests that exceed a budget are refused
before the change, and uncertain mutations are never retried automatically.

## Transport

| Limit | Value |
| --- | --- |
| Request body | 8 MiB |
| Response body | 8 MiB |
| Bridge queue | 8 pending requests |
| Default timeout | 60 seconds |
| Slow operation timeout | 300 seconds |
| Long operation timeout | 600 seconds |

Long operations: `remesh_quad`, `lod_chain` and `bake_map`.

## Scene and objects

| Limit | Value |
| --- | --- |
| `scene_info` page | 1–1000 objects |
| Name length | 63 UTF-8 bytes |
| Import name | 58 UTF-8 bytes |
| Custom mesh vertices | 3–10,000 |
| Custom mesh faces | 1–20,000 |
| Face size | 3–64 vertices |
| Face indices | 100,000 |
| Modifier stack | 16 modifiers |
| Evaluated bevel or subdivision | 500,000 faces |
| Duplicate objects | 1–256 |
| Join sources | 1–64 |
| Separate parts | 1–64 |
| Array copies | 2–1000 |
| Boolean inputs and result | 500,000 triangles |

## Geometry

| Limit | Value |
| --- | --- |
| General mesh operations | 500,000 triangles |
| `remesh_quad`, `collision`, `lightmap_uv`, `texel_density` | 200,000 triangles |
| `remesh_quad` target | 16–100,000 faces |
| LOD levels | 1–6 |
| Collision loose parts | 1–64 |
| Collision hull vertices | 4–255 |
| UV layers | 8 |
| Voxel size | 0.005–1 local units |
| Voxel bounding volume | 2,000,000 voxels |

## Rigging and animation

| Limit | Value |
| --- | --- |
| Armature bones | 128 |
| Binding bones | 64 |
| Binding meshes | 16 |
| Binding vertices | 50,000 |
| Weight repair vertices | 100,000 |
| Weight groups | 512 |
| Weight assignments | 1,000,000 |
| Inspected bones | 512 |
| Inspected vertices | 100,000 |
| Inspected triangles | 100,000 |
| Keyframes per action | 32 |
| Poses per frame | 128 |
| Poses per call | 2,048 |
| Animated export meshes | 64 |
| Animated export vertices | 100,000 |
| Animated export triangles | 200,000 |
| Animated export bones per armature | 128 |
| Animated export actions | 32 |
| Animation QA samples | 2–32 |
| Deformation vertex samples | 2,000,000 |
| Retarget armature bones | 512 |
| Retarget bone mappings | 128 |
| Retarget source frames | 1,000 |
| Retarget samples | 2–256 |
| Retarget keyframes | 100,000 |

## Materials and baking

| Limit | Value |
| --- | --- |
| Image size | 16 MiB |
| Image dimensions | 4096² |
| Combined material pixels | 32,000,000 |
| Material slots per inspection | 64 |
| Material nodes | 512 |
| Mesh shape keys including Basis | 64 |
| Rig actions in inventory | 64 |
| NLA strips per rig | 32 |
| Bake low-poly triangles | 200,000 |
| Bake high-poly triangles | 1,000,000 |
| Bake high-poly objects | 64 |
| Bake resolution | 4096 |
| Bake samples | 256 |
| Bake margin | 64 pixels |

## Imports

| Limit | Value |
| --- | --- |
| Source file | 64 MiB |
| GLB nodes | 1,000 |
| GLB vertices and triangles | 500,000 |
| GLB skins | 16 |
| GLB joints per skin | 512 |
| GLB total joints | 1,024 |
| GLB skinned meshes | 64 |
| GLB morph targets per mesh | 64 |
| GLB total morph targets | 256 |
| GLB influences per vertex | 4 |
| GLB animations | 32 |
| GLB channels and samplers | 1,024 |
| GLB keys per clip | 100,000 |
| GLB total keys | 256,000 |
| Embedded image dimensions | 4096², combined 4096² pixels |
| OBJ material libraries | 16 |
| OBJ textures | 64 |
| USD asset references | 128 |
| FBX sidecar textures | 64 files, 64 MiB |

## Previews and scatter

| Limit | Value |
| --- | --- |
| Preview resolution | 2048; Eevee 1024 |
| Review sheet width | 256–2048 |
| Review views | 6 |
| Review source triangles | 500,000 |
| Copy-based review modes | 200,000 triangles |
| Scatter collection objects | 256 |
| Estimated instances | 100,000 |
| Realized scatter triangles | 2,000,000 |

## Local generation

| Limit | Value |
| --- | --- |
| Input image | 16 MiB |
| Input dimensions | 4096 pixels per side |
| Resolution | 64–192 |
| Timeout | 180 seconds |
| Output GLB | 64 MiB |
| Output faces | 500,000 |

## Ownership

| Limit | Value |
| --- | --- |
| Lease duration | 30–3600 seconds |
| Default lease | 600 seconds |
| Owner label | 128 characters |

## Related

- [Security model](../security/model.md)
- [Troubleshooting](../guides/troubleshooting.md)
