# Cavi Blender MCP

**Big ideas. Still editable.**

[![PyPI version](https://img.shields.io/pypi/v/cavi-blender-mcp)](https://pypi.org/project/cavi-blender-mcp/) [![PyPI weekly downloads](https://img.shields.io/pypi/dw/cavi-blender-mcp?label=PyPI%20downloads%2Fweek)](https://pypistats.org/packages/cavi-blender-mcp) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

![A mole sculpts an armored llama balancing on red roller skates](media/blender-mcp-hero.png)

Give your assistant a direction, review the next pass and keep working in Blender. Cavi Blender MCP connects scene inspection, mesh and material edits, previews and export in one local workflow.

Try a request with your own working scene:

> Inspect this scene, refine the shape and materials, and show me a preview. Save the revision as a new Blender project so I can keep editing it.

You decide what to change and judge the result; your assistant operates Blender through Cavi.

## Install

You need [uv](https://docs.astral.sh/uv/), **Python 3.15+** and **Blender** on macOS or Linux. Native checks target Blender 5.3.0.

To use the current source, clone this repository and install its environment:

```bash
git clone https://github.com/cavi-ai/blender-mcp.git
cd blender-mcp
uv sync --locked
```

Place a working copy of your `.blend` file in `~/Documents/CaviBlender/`, the default workspace, then start the session and check its connection:

```bash
.venv/bin/cavi-blender-mcp runtime start --project working-copy.blend
.venv/bin/cavi-blender-mcp runtime status
```

Register the source environment's absolute `.venv/bin/cavi-blender-mcp` path as a local stdio server in your MCP client:

```json
{
  "mcpServers": {
    "blender": {
      "command": "/absolute/path/to/blender-mcp/.venv/bin/cavi-blender-mcp"
    }
  }
}
```

New sessions use factory settings without changing your usual preferences. An existing connected session may be reused; startup will not replace a different connected project. See [project startup](docs/blender-mcp/source/pages/guides/runtime-and-headless.md) and [installation](docs/blender-mcp/source/pages/introduction/installation.md) for options.

For the published release, install `cavi-blender-mcp==0.58.0` with `uv tool install`; use the [release documentation](https://github.com/cavi-ai/blender-mcp/tree/v0.58.0/docs/blender-mcp/source) for its supported features.

## Keep developing the asset

| You want to… | Your agent can… |
| --- | --- |
| [Understand the scene](docs/blender-mcp/source/pages/guides/scene-inspection.md) | Inspect objects, mesh quality, materials, UVs and rigs. |
| [Revise the shape](docs/blender-mcp/source/pages/guides/mesh-preparation.md) | Edit meshes, apply modifiers and organize parts. |
| [Refine a procedural asset](docs/blender-mcp/source/pages/guides/procedural-assets.md) | Adjust exposed Geometry Nodes inputs while keeping the authored node graph. |
| [Develop the surface](docs/blender-mcp/source/pages/guides/materials-and-uvs.md) | Assign PBR materials and textures, inspect UVs and bake maps. |
| [Judge the next pass](docs/blender-mcp/source/pages/guides/previews-and-review.md) | Produce PNG previews, lit Eevee views and review sheets. |
| [Take the work onward](docs/blender-mcp/source/pages/guides/asset-import-export.md) | Save the project or export supported GLB, FBX, OBJ, USD, STL, PLY and Alembic assets. |

[Local image-to-mesh generation](docs/blender-mcp/source/pages/guides/local-generation.md) is an optional route with separate model and worker setup.

## Local work, explicit ownership

The server and Blender bridge run on your machine. The bridge uses a private session token on loopback; Cavi provides no arbitrary Python tool, telemetry, remote inference or external asset downloads.

Your agent claims edit ownership for the current project before changing it. Saves, previews and exports stay inside the configured workspace and refuse existing output paths. If an operation times out, inspect the scene before trying again: the change may already have happened.

The default workspace is `~/Documents/CaviBlender`. See [configuration](docs/blender-mcp/source/pages/reference/configuration.md), [project ownership](docs/blender-mcp/source/pages/guides/session-ownership.md) and the [security model](docs/blender-mcp/source/pages/security/model.md) for the relevant settings and behavior. Report security issues through [SECURITY.md](SECURITY.md).

## Documentation and development

The source setup above follows this repository. The published package installs **0.58.0**; use its [tagged documentation](https://github.com/cavi-ai/blender-mcp/tree/v0.58.0/docs/blender-mcp/source) for that release. Check the version shown on the [documentation website](https://cavi-ai.xyz/docs/blender-mcp/) when following a guide there.

The server publishes 20 tools over stdio. The [tool reference](docs/blender-mcp/source/pages/reference/tools.md) documents exact operations, bounds and response contracts.

- **Using the tools:** [overview](docs/blender-mcp/source/pages/introduction/overview.md), [installation](docs/blender-mcp/source/pages/introduction/installation.md), [quickstart](docs/blender-mcp/source/pages/introduction/quickstart.md), [troubleshooting](docs/blender-mcp/source/pages/guides/troubleshooting.md).
- **Building an integration:** [tool reference](docs/blender-mcp/source/pages/reference/tools.md), [CLI](docs/blender-mcp/source/pages/reference/cli.md), [configuration](docs/blender-mcp/source/pages/reference/configuration.md), [limits](docs/blender-mcp/source/pages/reference/limits.md).
- **Contributing:** [development setup, tests and contribution guidance](CONTRIBUTING.md). Reproduction steps and a small project that demonstrates an issue make bug reports useful.
- **Following changes:** [changelog](CHANGELOG.md), [tags](https://github.com/cavi-ai/blender-mcp/tags) and [GitHub Releases](https://github.com/cavi-ai/blender-mcp/releases). The tool surface can change before 1.0.

## License

[MIT](LICENSE).
