# Generate a mesh locally

`asset_io` with `action="generate"` runs optional image-to-3D inference and
writes a new workspace `.glb`. It does not change the open scene and does not
need a lease.

The MCP process does not import PyTorch, download weights or send images to a
remote service. The worker runs in a separate Python 3.11 environment with local
weights.

## Prepare the worker

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

## Run

Put an image of one isolated object on white or transparency inside the
workspace, then call:

```json
{
  "action": "generate",
  "image": "references/prop.png",
  "path": "generated/prop.glb",
  "resolution": 128
}
```

Resolution is bounded to 64–192. Input images are at most 16 MiB and 4096 pixels
per side. Generation runs offline on CPU with four threads, chunked field
queries and a 180-second timeout. The output is published without replacing an
existing file.

The result includes object counts, the input SHA-256 and the output path.

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

Generated surfaces still need inspection, retopology, UV work, rigging and game
import validation.

## Related

- [Import and export assets](asset-import-export.md)
- [Configuration](../reference/configuration.md)
