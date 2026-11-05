# Generate a mesh locally

`asset_io` with `action="generate"` runs optional image-to-3D inference and
writes a new workspace `.glb`. It does not change the open scene and does not
need a lease.

The MCP process does not import PyTorch, download weights or send images to a
remote service. The worker runs in a separate Python 3.11 environment with local
weights.

Three providers are available. `CAVI_GENERATION_PROVIDER` selects one and
defaults to `triposr`.

| Provider | Output | Device | Timeout |
| --- | --- | --- | --- |
| `triposr` | Vertex-colored surface, resolution 64–192 | CPU, four threads | 180 seconds |
| `triposg` | Uncolored surface, at most 500,000 triangles | Apple Silicon (MPS), CUDA or CPU | 600 seconds |
| `triposg-mlx` | Uncolored surface, at most 500,000 triangles | Apple Silicon (MLX) through mlx-agent | 600 seconds |

## Prepare TripoSR

```bash
uv venv --python 3.11 /path/to/neural-env
uv pip install --python /path/to/neural-env/bin/python -r requirements-neural.txt
```

Check out upstream TripoSR at commit
`107cefdc244c39106fa830359024f6a2f1c78871`.

Download these files into one weights directory:

- `config.yaml` and `model.ckpt` from the public `stabilityai/TripoSR` model at
  revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`
- `facebook/dino-vitb16/config.json`, saved as `dino-config.json`

Configure absolute local paths in the MCP server environment:

```text
CAVI_TRIPOSR_PYTHON=/path/to/neural-env/bin/python
CAVI_TRIPOSR_SOURCE=/path/to/TripoSR
CAVI_TRIPOSR_WEIGHTS=/path/to/weights
```

## Prepare TripoSG

```bash
uv venv --python 3.11 /path/to/triposg-env
uv pip install --python /path/to/triposg-env/bin/python -r requirements-triposg.txt
```

Check out upstream TripoSG at commit
`fc5c40990181e2a756c4e0b1c2f4d6b5202faf8c`.

Download the public `VAST-AI/TripoSG` model at revision
`2c1c516d22d58db486a058d98d31bb6177344e06` into one weights directory. It holds
`model_index.json` and the `transformer`, `vae`, `scheduler`,
`image_encoder_dinov2` and `feature_extractor_dinov2` folders. The background
removal model is not used.

Configure absolute local paths in the MCP server environment:

```text
CAVI_GENERATION_PROVIDER=triposg
CAVI_TRIPOSG_PYTHON=/path/to/triposg-env/bin/python
CAVI_TRIPOSG_SOURCE=/path/to/TripoSG
CAVI_TRIPOSG_WEIGHTS=/path/to/TripoSG-weights
```

## Prepare TripoSG on MLX

`triposg-mlx` runs the same model without PyTorch through
`mlx-agent convert mesh` on Apple Silicon.

Install the `mlx-3d` backend with `mlx-agent backend install mlx-3d`, then
convert the public `VAST-AI/TripoSG` model to a 32-bit MLX model with
`mlx-agent convert start --q-bits 32`. The backend is found under
`$XDG_DATA_HOME/mlx-workbench/backends`, which defaults to `~/.local/share`.

Configure absolute local paths in the MCP server environment.
`CAVI_TRIPOSG_MLX_PYTHON` is a Python 3.11 or newer environment with Pillow. It
frames the image and runs the launcher.

```text
CAVI_GENERATION_PROVIDER=triposg-mlx
CAVI_TRIPOSG_MLX_PYTHON=/path/to/python
CAVI_TRIPOSG_MLX_AGENT=/path/to/mlx-agent/scripts/mlx-agent
CAVI_TRIPOSG_MLX_MODEL=/path/to/converted-triposg
```

## Run

Put an image of one isolated object on a plain background or transparency inside
the workspace, then call:

```json
{
  "action": "generate",
  "image": "references/prop.png",
  "path": "generated/prop.glb"
}
```

`resolution` applies only to TripoSR, defaults to 128 and is bounded to 64–192.
Both TripoSG providers refuse it. Input images are at most 16 MiB and 4096
pixels per side. An existing transparent cutout is used as provided. An opaque
image loses the plain background that frames its border, in any colour, while
colours the object encloses stay; an opaque image without a plain background is
refused. The output is published without replacing an existing file.

TripoSG runs 50 sampling steps with a fixed seed, extracts the surface on a
512³ grid and reduces it to at most 500,000 triangles. On an Apple M5 Max a
character takes about two minutes.

`triposg-mlx` frames the image exactly like `triposg`, then runs 50 sampling
steps with seed 42 and a 512³ grid and reduces the surface to at most 500,000
faces. `triposg` uses seed 0, so the two providers return different meshes. A
character takes two to three minutes and peaks near 10 GB of memory. The agent
stops itself 30 seconds before the timeout and reports why.

The result includes the provider, device, object counts, the input SHA-256 and
the output path. `triposg-mlx` returns `backend`, `vertices`, `faces`, `seconds`,
`stage_seconds` and `peak_memory_gb` instead of the device and triangle count.

## Continue

Import the generated GLB with `asset_io`:

```json
{
  "action": "import",
  "path": "generated/prop.glb",
  "name": "Prop",
  "lease_id": "<lease_id>"
}
```

Generated surfaces still need inspection, decimation to the asset budget,
retopology, UV work, rigging and game import validation.

## Related

- [Import and export assets](asset-import-export.md)
- [Configuration](../reference/configuration.md)
