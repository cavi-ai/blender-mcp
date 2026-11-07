# Cavi Blender MCP

**Bring your idea. Keep shaping it in Blender.**

[![PyPI version](https://img.shields.io/pypi/v/cavi-blender-mcp)](https://pypi.org/project/cavi-blender-mcp/) [![PyPI downloads](https://img.shields.io/pypi/dw/cavi-blender-mcp?label=PyPI%20downloads)](https://pypistats.org/packages/cavi-blender-mcp) [![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Cavi connects your agent to a real Blender project. Give it a direction, review the next pass, and keep working in the same editable scene. Your agent can inspect the project, change geometry and materials, show you a preview, and save or export the result.

![Night Watch Lantern: an indigo-and-brass harbor lantern framed by an oversized crescent](examples/creator-directed-revision/after.png)

## Give the lantern a night shift

The crescent stays. The rest needs to survive a harbor night.

> Keep the oversized crescent and brass pivot. Make this feel like a working harbor signal: lower and widen the storm hood, give it a broader stance, protect the lamp with a ribbed guard, and use indigo enamel with a warmer amber light. Show me the revision before saving a new copy. Leave the parts editable.

[Compare the two designs and open the Blender files →](examples/creator-directed-revision/README.md)

Use the example as a starting point, or bring a working copy of your own project. You choose what to change and judge the result; the agent operates Blender through Cavi.

## Install

You need [uv](https://docs.astral.sh/uv/), **Python 3.11+** and **Blender**. The published 0.56.0 package targets macOS and Linux; native checks target Blender 5.2.3 LTS.

Save the [starting scene](examples/creator-directed-revision/before.blend) as `before.blend` in `~/Documents/CaviBlender/`, the default workspace. Create that folder if needed. Install Cavi and start with this project:

```bash
uv tool install cavi-blender-mcp==0.56.0
cavi-blender-mcp runtime start --project before.blend
```

Newly launched sessions use factory settings without loading or saving your usual preferences. An existing connected session may be reused; `start` will not replace a different connected project. See [project startup](https://github.com/cavi-ai/blender-mcp/blob/v0.56.0/docs/blender-mcp/source/pages/guides/runtime-and-headless.md) if you already use Cavi. Blender is found through `PATH`, `CAVI_BLENDER_BIN`, or the standard macOS application path.

Add Cavi to your agent's MCP configuration:

```json
{
  "mcpServers": {
    "blender": {
      "command": "cavi-blender-mcp"
    }
  }
}
```

If your client does not inherit your shell's `PATH`, use the full path printed by `which cavi-blender-mcp`. The agent must support local stdio MCP servers.

Then ask your agent:

> Inspect the lantern in the connected scene. Make the harbor-signal revision above, then show me a preview. Save the revised scene as a new `.blend` file and keep its parts editable.

To work on your own asset, start Cavi with a working copy of that project instead. The [installation guide](https://github.com/cavi-ai/blender-mcp/blob/v0.56.0/docs/blender-mcp/source/pages/introduction/installation.md) covers the remaining setup options.

## Keep developing the asset

| You want to… | Your agent can… |
| --- | --- |
| [Understand the scene](docs/blender-mcp/source/pages/guides/scene-inspection.md) | Inspect objects, mesh quality, materials, UVs and rigs. |
| [Revise the shape](docs/blender-mcp/source/pages/guides/mesh-preparation.md) | Edit meshes, apply modifiers and organize parts. |
| [Develop the surface](docs/blender-mcp/source/pages/guides/materials-and-uvs.md) | Assign PBR materials and textures, inspect UVs and bake maps. |
| [Judge the next pass](docs/blender-mcp/source/pages/guides/previews-and-review.md) | Produce PNG previews, lit Eevee views and review sheets. |
| [Take the work onward](docs/blender-mcp/source/pages/guides/asset-import-export.md) | Save the project or export supported GLB, FBX, OBJ and USD assets. |

For a narrower production example, [the material handoff](examples/material-texture-sets/README.md) follows a utility case's material assignments into Painter texture sets. [Local image-to-mesh generation](docs/blender-mcp/source/pages/guides/local-generation.md) is an optional route with separate model and worker setup.

## Local work, explicit ownership

The server and Blender bridge run on your machine. The bridge uses a private session token on loopback; Cavi provides no arbitrary Python tool, telemetry, remote inference or external asset downloads.

Your agent claims edit ownership for the current project before changing it. Saves, previews and exports stay inside the configured workspace and refuse existing output paths. If an operation times out, inspect the scene before trying again: the change may already have happened.

The default workspace is `~/Documents/CaviBlender`. See [configuration](docs/blender-mcp/source/pages/reference/configuration.md), [project ownership](docs/blender-mcp/source/pages/guides/session-ownership.md) and the [security model](docs/blender-mcp/source/pages/security/model.md) for the relevant settings and behavior. Report security issues through [SECURITY.md](SECURITY.md).

## Documentation and development

The first-use steps above use the **published 0.56.0 package**. [Its tagged documentation](https://github.com/cavi-ai/blender-mcp/tree/v0.56.0/docs/blender-mcp/source) matches that version. The documentation in this checkout follows current source, which requires **Python 3.15+**. Check the version shown on the [documentation website](https://cavi-ai.xyz/docs/blender-mcp/) when following a guide there.

The server publishes 20 tools over stdio. The [tool reference](docs/blender-mcp/source/pages/reference/tools.md) documents exact operations, bounds and response contracts.

- **Using the tools:** [overview](docs/blender-mcp/source/pages/introduction/overview.md), [installation](docs/blender-mcp/source/pages/introduction/installation.md), [quickstart](docs/blender-mcp/source/pages/introduction/quickstart.md), [troubleshooting](docs/blender-mcp/source/pages/guides/troubleshooting.md).
- **Building an integration:** [tool reference](docs/blender-mcp/source/pages/reference/tools.md), [CLI](docs/blender-mcp/source/pages/reference/cli.md), [configuration](docs/blender-mcp/source/pages/reference/configuration.md), [limits](docs/blender-mcp/source/pages/reference/limits.md).
- **Contributing:** [development setup, tests and contribution guidance](CONTRIBUTING.md). Reproduction steps and a small project that demonstrates an issue make bug reports useful.
- **Following changes:** [changelog](CHANGELOG.md), [tags](https://github.com/cavi-ai/blender-mcp/tags) and [GitHub Releases](https://github.com/cavi-ai/blender-mcp/releases). The tool surface can change before 1.0.

## License

[MIT](LICENSE).
