# Configuration

Configuration is environment-based. Set a variable in both Blender's environment
and the MCP server's environment when both processes read it.

## Bridge and server

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAVI_BLENDER_WORKSPACE` | `~/Documents/CaviBlender` | Workspace for saves, exports, previews, imports and generated assets |
| `CAVI_BLENDER_CONNECTION` | `~/.cavi/blender-mcp/connection.json` | Private connection file with loopback port, token and pid |
| `CAVI_BLENDER_BIN` | Blender on `PATH`, or the standard macOS app path | Executable used by `runtime start` |

The workspace is created when missing. Save, export, preview and bake paths must
remain inside it, including through symbolic links. Existing files are refused
and parent directories must already exist.

Separate concurrent Blender sessions need separate connection files. Keep the
connection file out of repositories.

## Local image-to-3D

These are read by the MCP server. All must be absolute local paths.

| Variable | Purpose |
| --- | --- |
| `CAVI_TRIPOSR_PYTHON` | Python 3.11 worker environment |
| `CAVI_TRIPOSR_SOURCE` | TripoSR checkout |
| `CAVI_TRIPOSR_WEIGHTS` | Directory with `config.yaml`, `model.ckpt` and `dino-config.json` |

The worker sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`HF_HUB_DISABLE_IMPLICIT_TOKEN=1` and `OMP_NUM_THREADS=4`. See
[Generate a mesh locally](../guides/local-generation.md).

## MCP client

Register the installed entry point and pass the variables through `env`:

```json
{
  "mcpServers": {
    "blender": {
      "command": "cavi-blender-mcp",
      "env": {
        "CAVI_BLENDER_CONNECTION": "/Users/me/.cavi/blender-mcp/connection.json",
        "CAVI_BLENDER_WORKSPACE": "/Users/me/Documents/CaviBlender"
      }
    }
  }
}
```

The bridge binds only to `127.0.0.1` on an ephemeral port. The server makes no
external network requests.

## Related

- [CLI](cli.md)
- [Security model](../security/model.md)
- [Installation](../introduction/installation.md)
