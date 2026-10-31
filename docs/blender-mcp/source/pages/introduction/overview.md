# Blender MCP overview

Blender MCP {{PRODUCT_VERSION}} gives MCP clients typed, bounded control of a
Blender session. It has two parts:

- **The MCP server**: a stdio server that publishes 13 tools and forwards
  requests to the bridge.
- **The Blender bridge**: a Python module loaded inside Blender that executes
  operations on Blender's main thread.

Everything runs on the local machine. The bridge binds only to IPv4 loopback and
requires a random session token. There is no arbitrary Python tool, telemetry,
external asset download or remote inference.

## What it covers

- **Inspection**: scene and object metadata, mesh budgets, texel density,
  directional UV stretch, material bindings, bone hierarchies, skin weights and
  linked clips.
- **Object editing**: primitives, custom meshes, transforms, origins, snapping,
  names, sockets, duplicates, parents and collections.
- **Mesh preparation**: modifiers, UV unwrapping, decimation, LOD chains,
  QuadriFlow remeshing, lightmap packing, texel-density correction, collision
  hulls, cleanup, booleans, joins, splits, mirrors, arrays and shells.
- **Materials**: PBR slot assignment with packed workspace textures, UV
  transforms, alpha modes and material QA.
- **Baking**: normal and ambient-occlusion maps into a new workspace PNG.
- **Assets**: bounded GLB, FBX, OBJ and USD import; static, skinned and animated
  FBX/GLB export; USD export; Unity, Unreal and Godot axis presets; LOD groups,
  collision naming and bake pairs.
- **Rigging**: armature creation, automatic skin binding, weight repair, pose
  authoring, action creation, animation QA and retargeting.
- **Previews**: isolated PNG previews, lit Eevee previews and multi-view review
  sheets.
- **Scatter**: fixed Geometry Nodes instancing with explicit budgets.
- **Ownership**: edit leases shared by independent MCP clients.
- **Evaluation**: deterministic protocol and native application checks through
  `@cavi-ai/mcp-eval`.

[Tools](../reference/tools.md) lists every tool and action. Start with
[Inspect a scene](../guides/scene-inspection.md) or
[Import and export assets](../guides/asset-import-export.md).

## Evaluation

`npm run eval:protocol` checks discovery size, catalog token budgets, pagination,
surface listing and protocol negotiation. `npm run eval:core -- --blender
/path/to/blender` adds schema, structured output, repeated reads, contention and
native application cases.

Native evaluation starts its own factory scene with a private connection and
disposable workspace. It does not connect to an existing session. Reports stay
under `.tmp/evals/` and are ignored by Git. The evaluator does not invoke a
model; results do not establish model task quality or game integration.

## Boundaries

- Blender's operators and the render engine remain the source of truth. The
  server reports refusals instead of simulating unsupported edits.
- Materials, shading and UV edits refuse shared mesh data. Make the mesh
  single-user in Blender first.
- Exported assets still need the destination game's materials, scale, collision
  and import settings.
- The optional image-to-3D worker produces a mesh; it does not rig, animate or
  validate game import quality.
- Native checks target Blender 5.2.3 LTS. Behavior may differ on older releases.

The [limits reference](../reference/limits.md) lists every input and output
budget. The [security model](../security/model.md) describes the transport,
filesystem and ownership boundaries.

These docs were generated for release {{RELEASE_TAG}} from commit
`{{RELEASE_COMMIT}}`.
