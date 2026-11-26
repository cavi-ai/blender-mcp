# Configuration

Configuration is environment-based. Set a variable in both Blender's environment
and the MCP server's environment when both processes read it.

## Bridge and server

| Variable | Default | Purpose |
| --- | --- | --- |
| `CAVI_BLENDER_WORKSPACE` | `~/Documents/CaviBlender` | Workspace for saves, exports, previews, imports and generated assets; an absolute path |
| `CAVI_BLENDER_CONNECTION` | `~/.cavi/blender-mcp/connection.json` | Private connection file with loopback port, token and pid |
| `CAVI_BLENDER_BIN` | The standard macOS app path, or Blender on `PATH` | Executable used by `runtime start` and `extension install` |

The workspace is created when missing. Save, export, preview and bake paths must
remain inside it, including through symbolic links. Existing files are refused
and parent directories must already exist.

Separate concurrent Blender sessions need separate connection files. Keep the
connection file out of repositories.

## Local image-to-3D

These are read by the MCP server. All must be absolute local paths.

| Variable | Purpose |
| --- | --- |
| `CAVI_GENERATION_PROVIDER` | `triposr` (default), `triposg`, `triposg-mlx` or `trellis2-mlx` |
| `CAVI_TRIPOSR_PYTHON` | Python 3.12 worker environment |
| `CAVI_TRIPOSR_SOURCE` | TripoSR checkout |
| `CAVI_TRIPOSR_WEIGHTS` | Directory with `config.yaml`, `model.ckpt` and `dino-config.json` |
| `CAVI_TRIPOSG_PYTHON` | Python 3.12 worker environment |
| `CAVI_TRIPOSG_SOURCE` | TripoSG checkout |
| `CAVI_TRIPOSG_WEIGHTS` | Local `VAST-AI/TripoSG` model directory |
| `CAVI_TRIPOSG_MLX_PYTHON` | Python 3.11 or newer with Pillow; frames the image and runs the launcher |
| `CAVI_TRIPOSG_MLX_AGENT` | `mlx-agent` launcher script |
| `CAVI_TRIPOSG_MLX_MODEL` | Converted TripoSG model directory |
| `CAVI_TRELLIS2_MLX_PYTHON` | Python 3.11 or newer with Pillow; frames the image and runs the launcher |
| `CAVI_TRELLIS2_MLX_AGENT` | `mlx-agent` launcher script |
| `CAVI_TRELLIS2_MLX_MODEL` | Converted TRELLIS.2 model directory |
| `CAVI_IMAGE_MLX_PYTHON` | Python 3.11 or newer with Pillow; wraps the panorama seam and runs the launcher |
| `CAVI_IMAGE_MLX_AGENT` | `mlx-agent` launcher script |
| `CAVI_IMAGE_MLX_MODEL` | Converted image-generation model directory for `generate` with `prompt` |

Only the selected provider's paths are required. The worker sets `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`,
`HF_HUB_DISABLE_IMPLICIT_TOKEN=1` and `OMP_NUM_THREADS` to the configured `THREADS`. `triposg-mlx` and
`trellis2-mlx` find the mlx-agent backend under `$XDG_DATA_HOME/mlx-workbench/backends`. See
[Generate a mesh locally](../guides/local-generation.md).

## Generation settings

Each setting is read from `<PREFIX>_<QUALITY>_<NAME>`, then `<PREFIX>_<NAME>`, then the default below.
`<PREFIX>` is the provider's variable prefix (`CAVI_TRIPOSR`, `CAVI_TRIPOSG`, `CAVI_TRIPOSG_MLX`,
`CAVI_TRELLIS2_MLX`, or `CAVI_IMAGE_MLX` for panoramas) and `<QUALITY>` is `FAST`, `DEFAULT` or `HIGH`. For
example, `CAVI_TRELLIS2_MLX_HIGH_TIMEOUT=3000` raises only the `high` tier's limit, while
`CAVI_TRELLIS2_MLX_TIMEOUT` applies to every tier without its own value. Numbers are integers except
`GUIDANCE` and `WHITE`; a value outside its range is refused before any work starts.

| Name | Applies to | Default |
| --- | --- | --- |
| `TIMEOUT` | Every provider; seconds | `triposr` 180, `triposg` 600, `triposg-mlx` 600, `trellis2-mlx` 600 (`high` 3000), panorama 1800 |
| `THREADS` | Mesh providers; `OMP_NUM_THREADS` | 4 |
| `SEED` | Every provider; 0 or more | `triposr` 0, `triposg` 0, MLX mesh providers 42, panorama 42 |
| `STEPS` | `triposg`, MLX providers, panorama | `triposg` 50; `triposg-mlx` 50 (`fast` 25); `trellis2-mlx` the checkpoint's (`fast` 6); panorama 30 (`fast` 12) |
| `RESOLUTION` | `triposr` (64–192, a request `resolution` wins), MLX mesh providers | `triposr` 128; `triposg-mlx` 512 (`fast` 256); `trellis2-mlx` 512 (`high` 1024) |
| `DENOISER_CACHE` | `triposg-mlx` | `off` (`fast` `adaptive`) |
| `GUIDANCE` | `triposg`; 0 or more | 7.0 |
| `MAX_FACES` | Mesh providers | 500,000; `trellis2-mlx` `fast` and `high` 166,666 |
| `CHUNK_SIZE` | `triposr` renderer | 16384 |
| `WIDTH` | Panorama; even, height is half | 2048 |
| `SEAM_BAND` | Panorama; under half the width | 128 |
| `WHITE` | Panorama EXR; 1.0 or more | 16.0 |

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

Native RPC error envelopes may include `error_outcome: rejected` for explicitly
verified preflight failures. The field is optional and accompanies the error
string and matching request ID. Missing, unknown or malformed outcome metadata
does not establish rejection. The MCP error result keeps `retry_safe: false`.
