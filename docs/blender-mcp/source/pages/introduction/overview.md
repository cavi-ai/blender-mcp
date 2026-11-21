# Blender MCP overview

Blender MCP {{PRODUCT_VERSION}} gives MCP clients typed, bounded control of a
Blender session. It has two parts:

- **The MCP server**: a stdio server that publishes 20 tools and forwards
  requests to the bridge.
- **The Blender bridge**: a Python module loaded inside Blender that executes
  operations on Blender's main thread. `cavi-blender-mcp runtime start` loads it
  into a background Blender; the Blender extension loads it into your own
  interactive Blender.

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
  transforms, alpha modes, shader node authoring and material QA.
- **Baking**: normal, ambient-occlusion, curvature, lightmap, vertex color,
  vertex ORM and shader socket maps into a new workspace PNG; shader socket
  maps can also write EXR.
- **Assets**: bounded GLB, FBX, OBJ, USD, STL, PLY and Alembic import; static,
  skinned and animated FBX, GLB and USD export; static OBJ, STL, PLY and Alembic
  export; Unity, Unreal and Godot axis presets; LOD groups,
  collision naming and bake pairs.
- **Rigging**: armature creation, Rigify metarigs and generated rigs, automatic
  skin binding, weight repair, pose authoring, action creation, animation QA,
  motion comparison, skin clearance and retargeting.
- **Scenes**: cameras, lights, world lighting and final renders.
- **Procedural assets**: Geometry Nodes inputs and static bakes, and appending
  objects, collections, materials and node groups from workspace `.blend` files.
- **Previews**: isolated PNG previews, lit Eevee previews and multi-view review
  sheets.
- **Levels**: bounded terrain meshes, bulk placement and surface snapping.
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

CI runs both modes with Blender 5.3.0. Native evaluation supplies fixture
arguments for all six read-only tools and enforces catalog, protocol, error,
reliability and coverage checks. Catalog budgets bound discovery costs. Latency
is excluded from readiness floors because it depends on the runner.

CI builds the evaluator directly from `cavi-ai/mcp-eval`'s `main` branch and
retains Cargo's resolved revision. Local runs use the installed npm evaluator
by default. Set `MCPEVAL_EXECUTABLE` to use another executable, and
`MCPEVAL_SOURCE_REVISION` to record its source revision. `evaluator.json` records
the entry point, version and npm wrapper resolution separately: following the
wrapper's Git branch does not imply that its release binary was built from that commit.

Native evaluation starts its own factory scene with a private connection and
disposable workspace. It does not connect to an existing session. Reports stay
under `.tmp/evals/` and are ignored by Git. The evaluator does not invoke a
model; results do not establish model task quality or game integration.

## Boundaries

- Blender's operators and the render engine remain the source of truth. The
  server reports refusals instead of simulating unsupported edits. Sculpt is
  refused in background mode, and a stroke that does not move vertices is refused.
  Volume import accepts an OpenVDB file and does not invent grid data.
- Materials, shading and UV edits refuse shared mesh data. Make the mesh
  single-user in Blender first.
- Exported assets still need the destination game's materials, scale, collision
  and import settings.
- The optional image-to-3D worker produces a mesh; it does not rig, animate or
  validate game import quality.
- Native checks target Blender 5.3.0. Behavior may differ on older releases.

The [limits reference](../reference/limits.md) lists every input and output
budget. The [security model](../security/model.md) describes the transport,
filesystem and ownership boundaries.

These docs were generated for release {{RELEASE_TAG}} from commit
`{{RELEASE_COMMIT}}`.
