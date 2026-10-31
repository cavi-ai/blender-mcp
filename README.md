# Blender MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local-first MCP tools for Blender scene inspection, mesh editing, previews and
game asset export. The server publishes 14 tools over stdio and sends every
operation to a bridge that runs on Blender's main thread.

Everything runs on the local machine. The bridge binds only to IPv4 loopback and
requires a random session token. There is no arbitrary Python tool, telemetry,
external asset download or remote inference.

## Install

Requirements: Python 3.11 or newer, [`uv`](https://docs.astral.sh/uv/), and
Blender. Native checks target Blender 5.2.3 LTS. Dependencies are pinned in
`uv.lock`.

```bash
git clone https://github.com/cavi-ai/blender-mcp.git
cd blender-mcp
uv sync --locked
```

Start a dedicated Blender session with the bridge. Use the absolute path to this
checkout:

```bash
blender --factory-startup --python /path/to/blender-mcp/scripts/start_bridge.py
```

`--factory-startup` opens a separate default scene without loading or saving user
preferences. The stdio MCP server never launches or authenticates Blender by
itself; use the runtime CLI when you want it to start a dedicated session.

## Quickstart

Register the installed entry point with your MCP client:

```json
{
  "mcpServers": {
    "blender": {
      "command": "/path/to/blender-mcp/.venv/bin/cavi-blender-mcp"
    }
  }
}
```

Call `scene_info` first. Then inspect the session with `session_control`:

```json
{"action": "inspect"}
```

Claim the returned `project_id` and pass the returned `lease_id` on mutations:

```json
{
  "action": "claim",
  "owner": "asset-agent",
  "expected_project": "<project_id>",
  "ttl_seconds": 600
}
```

Make a bounded change with `object_edit`:

```json
{
  "action": "create_primitive",
  "name": "Crate_01",
  "kind": "cube",
  "lease_id": "<lease_id>"
}
```

Read-only calls do not need a lease. Release or expiry never saves, closes or
discards a project. See the
[ownership guide](docs/blender-mcp/source/pages/guides/session-ownership.md).

You can also let the CLI manage the session:

```bash
cavi-blender-mcp runtime start
cavi-blender-mcp runtime status
cavi-blender-mcp runtime restart --lease-id <current-lease>
```

## What it does

- **Inspection**: scene and object metadata, mesh budgets, texel density, UV
  stretch, material bindings, bone hierarchies and skin weights.
- **Object editing**: primitives, custom meshes, transforms, origins, names,
  sockets, duplicates, parents, collections and shape keys.
- **Mesh preparation**: modifiers, UV unwrapping, decimation, LOD chains,
  QuadriFlow, lightmap packing, texel density, collision hulls, cleanup,
  booleans, joins, splits, mirrors, arrays and shells.
- **Materials**: PBR slot assignment with packed workspace textures, UV
  transforms, alpha modes and material QA.
- **Baking**: normal, ambient-occlusion, curvature and lightmap maps into a new
  workspace PNG.
- **Assets**: bounded GLB, FBX, OBJ and USD import; GLB morph targets and
  shape-key animation; static, skinned and animated FBX/GLB export; FBX and USD
  texture sidecars; USD export; Unity, Unreal and Godot axis presets; LOD groups,
  collision naming and bake pairs.
- **Rigging**: armature creation, automatic skin binding, weight repair, pose
  authoring, action creation, clip/NLA management, animation QA and retargeting.
- **Previews**: isolated PNG previews, lit Eevee previews and multi-view review
  sheets.
- **Levels**: heightmap or procedural terrain, bulk placement and surface snapping.
- **Scatter**: fixed Geometry Nodes instancing with explicit budgets.
- **Ownership**: edit leases shared by independent MCP clients.

Every input and output is bounded. When Blender does not expose an operation,
the server reports the boundary and fails closed instead of simulating a write.

## Documentation

The versioned documentation is published to
[cavi-ai.xyz/docs/blender-mcp](https://cavi-ai.xyz/docs/blender-mcp). The source
lives in this repository.

- [Overview](docs/blender-mcp/source/pages/introduction/overview.md),
  [Installation](docs/blender-mcp/source/pages/introduction/installation.md),
  [Quickstart](docs/blender-mcp/source/pages/introduction/quickstart.md)
- [Inspect a scene](docs/blender-mcp/source/pages/guides/scene-inspection.md)
- [Prepare meshes](docs/blender-mcp/source/pages/guides/mesh-preparation.md)
- [Materials and UVs](docs/blender-mcp/source/pages/guides/materials-and-uvs.md)
- [Import and export assets](docs/blender-mcp/source/pages/guides/asset-import-export.md)
- [Generate a mesh locally](docs/blender-mcp/source/pages/guides/local-generation.md)
- [Rig and animate](docs/blender-mcp/source/pages/guides/rigging-and-animation.md)
- [Preview and review](docs/blender-mcp/source/pages/guides/previews-and-review.md)
- [Tools](docs/blender-mcp/source/pages/reference/tools.md),
  [CLI](docs/blender-mcp/source/pages/reference/cli.md),
  [Configuration](docs/blender-mcp/source/pages/reference/configuration.md),
  [Limits](docs/blender-mcp/source/pages/reference/limits.md)
- [Security model](docs/blender-mcp/source/pages/security/model.md)
- [Troubleshooting](docs/blender-mcp/source/pages/guides/troubleshooting.md)

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAVI_BLENDER_WORKSPACE` | `~/Documents/CaviBlender` | Workspace for saves, exports, previews, imports and generated assets |
| `CAVI_BLENDER_CONNECTION` | `~/.cavi/blender-mcp/connection.json` | Private connection file with loopback port, token and pid |
| `CAVI_BLENDER_BIN` | Blender on `PATH`, or the standard macOS app path | Executable used by `runtime start` |
| `CAVI_TRIPOSR_PYTHON` | unset | Python 3.11 environment for optional local image-to-3D |
| `CAVI_TRIPOSR_SOURCE` | unset | TripoSR checkout |
| `CAVI_TRIPOSR_WEIGHTS` | unset | Local TripoSR weights directory |

Set a variable in both Blender's environment and the MCP server's environment
when both processes read it. See [configuration](docs/blender-mcp/source/pages/reference/configuration.md).

## Security

The bridge listens on loopback and requires a random bearer token from a private
connection file. Mutations require a claimed edit lease bound to the current
project. Paths are confined to the workspace, including through symbolic links,
and existing outputs are never overwritten. Changes are never retried after a
timeout; inspect the scene before resubmitting an uncertain mutation.

See the [security model](docs/blender-mcp/source/pages/security/model.md) and
[SECURITY.md](SECURITY.md).

## Tests

```bash
uv sync --locked --dev
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
npm ci
npm run eval:protocol
```

The unit suite does not need Blender. Native checks under `tests/blender_*.py`
run against a disposable factory scene and an empty workspace, including
animation QA and retargeting:

```bash
blender --background --factory-startup --python-exit-code 1 \
  --python tests/blender_smoke.py -- /path/to/empty/workspace
```

Docs are built and verified with:

```bash
uv run --locked python -m scripts.docs.build
uv run --locked python -m scripts.docs.verify
```

`npm run eval:protocol` checks discovery size, catalog token budgets,
pagination, surface listing and protocol negotiation. `npm run eval:core` adds
native application checks and requires Blender. See
[MCP evaluation](docs/blender-mcp/source/pages/introduction/overview.md#evaluation).

## Project status

See [GitHub Releases](https://github.com/cavi-ai/blender-mcp/releases) and the
[changelog](CHANGELOG.md). The tool surface can still change before 1.0.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. Third-party product names belong to their owners. No vendor assets, logos
or presets are included, and no endorsement is implied.
