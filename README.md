# Cavi Blender MCP

Typed MCP tools for Blender scene inspection, mesh editing, previews, and game asset export.

## Install

Requires Python 3.11+, uv, and Blender. Native import and runtime checks have been exercised with Blender 5.2.3 LTS. Dependencies are pinned in `uv.lock`.

```sh
uv sync --locked
```

Start a dedicated Blender session with the bridge. Use your Blender executable and the absolute path to this checkout:

```sh
blender --factory-startup --python /path/to/blender-mcp/scripts/start_bridge.py
```

`--factory-startup` opens a separate default scene without loading or saving user preferences. To use an existing project, explicitly open its working copy in this dedicated session. The bridge grants access to scene contents; use only trusted local MCP clients.

Register the stdio server in your MCP client:

```json
{"mcpServers":{"blender":{"command":"/path/to/blender-mcp/.venv/bin/cavi-blender-mcp"}}}
```

Call `scene_info` first. The bridge must be running inside Blender; the stdio MCP server does not launch an application or authenticate accounts. Use the explicit runtime CLI to start a dedicated Blender session when needed.

### Runtime commands

```sh
cavi-blender-mcp runtime start
cavi-blender-mcp runtime start --project working-copy.blend
cavi-blender-mcp runtime status
cavi-blender-mcp runtime restart --lease-id <current-lease>
```

`start` reuses a connected session or launches Blender with factory settings, embedded
script auto-execution disabled, and the packaged bridge. It starts only when the prior
connection is missing or refused; timeouts and uncertain failures leave existing sessions
untouched. `--project` selects an existing workspace-relative `.blend` and refuses to
replace a different connected project. `CAVI_BLENDER_BIN` overrides executable discovery;
otherwise the CLI uses Blender on PATH or the standard macOS installation. The connection
file and workspace environment variables select the dedicated session. Launch acceptance
does not prove readiness; require a successful status check before asset operations.

`status` and `restart` control the bridge inside an already running Blender session. Restart replaces
its local listener and credentials, then checks the new connection. It preserves the Blender
process, open scene, unsaved edits, and selection. A failed request is never automatically retried.
Commands print JSON and exit nonzero on failure. `CAVI_BLENDER_CONNECTION` selects
the session to control. Sessions started with an older bridge need to be reopened with the
updated `start_bridge.py` once before these commands are available.

Runtime restart does not reload Python source or refresh an MCP client's cached tool catalog.
After installing new tools, restart that client's MCP connection to discover them. Running
`cavi-blender-mcp` without arguments continues to serve MCP over stdio.

## Tools

- `session_control`: inspect, claim, renew, or release application edit ownership.
- `scene_info`, `object_info`: inspect scene and geometry.
- `create_primitive`, `transform_object`, `set_color`: create and edit objects.
- `create_mesh`: indexed custom geometry, with bounded vertices, faces and coordinates.
- `generate_mesh`: reconstruct a colored GLB from one original image using a configured local TripoSR worker.
- `import_mesh`: import a self-contained static GLB into a new named collection, preserving existing objects and selection.
- `add_modifier`, `shade_mesh`, `unwrap_mesh`: bevel, decimation, subdivision, voxel remeshing, shading and UVs.
- `export_mesh`: export named meshes as FBX or GLB.
- `save_project`: save a new Blender project.
- `render_preview`: render a PNG and return an MCP image. Optional mesh names isolate an asset; a camera direction selects its view. Visibility and camera settings are restored afterward.

Materials are Blender preview colors. Exported assets still need the destination game's materials, scale, collision and import settings.
Material, shading and UV edits refuse shared mesh data to avoid changing linked objects implicitly. Make the mesh single-user in Blender before editing it.

## File and connection boundaries

`CAVI_BLENDER_WORKSPACE` selects the output workspace, defaulting to `~/Documents/CaviBlender`. Save/export/preview paths must remain inside it, including through symbolic links. Existing files are refused. Parent directories must already exist.

The bridge binds only to `127.0.0.1` on an ephemeral port and requires a random session token. `CAVI_BLENDER_CONNECTION` selects its private connection file, defaulting to `~/.cavi/blender-mcp/connection.json`. Keep it out of repositories. Separate concurrent sessions require separate connection files configured in both Blender and the MCP server.

There is no arbitrary Python tool, telemetry or external asset download. Changes are not retried after a timeout; inspect the scene before resubmitting an uncertain mutation. Blender operations run on the main thread. The bridge stops when its Blender process exits.

Custom meshes accept 3–10,000 vertices, 1–20,000 faces and at most 100,000 face indices within the 1-MiB request limit. Faces use zero-based indices and outward winding. Invalid indices, repeated vertices and zero-area faces are refused before creating a Blender datablock. Disconnected shells are allowed for voxel fusion. Subdivision supports integer levels 1–3 within 500,000 estimated faces; remeshing requires a voxel size of 0.005–1 local units within a two-million-voxel bounding volume. Both organic modifiers require an object without existing modifiers to bound evaluation cost.

`add_modifier` defaults to a non-destructive modifier. Its optional `apply` flag bakes the result into a single-user mesh without an existing modifier stack, allowing fusion, smoothing and reduction in sequence.

## Local image-to-3D

Generation is optional and runs in a separate Python 3.11 environment. The MCP process does not import PyTorch, download weights or send images to a remote service. The worker uses [TripoSR](https://github.com/VAST-AI-Research/TripoSR), with CPU mesh extraction through scikit-image. Code and weights are MIT licensed. Its generated surfaces still require inspection, animation rigging and game import work.

After generation, call `import_mesh(path, name)` with that workspace-relative GLB and
a new asset name. Returned object names can be used with the editing and export tools.
Imports preserve transforms, UVs, and vertex colors; embedded images are packed into
Blender. A failed import removes its new datablocks and restores selection. The source
file is hashed, validated, and copied to a private snapshot before Blender reads it.

Import is limited to one-scene static triangle GLBs of at most 64 MiB, 1000 nodes,
500,000 vertices and triangles, and a combined 4096×4096 embedded-image pixels. PNG and JPEG
images may be embedded; external dependencies, animation, skins, cameras, compressed
geometry, and cyclic or excessively deep node hierarchies are refused. Rigged assets
need their own import workflow.
Import names accept at most 58 UTF-8 bytes to leave room for object suffixes.

Prepare a separate runtime with `uv venv --python 3.11 /path/to/neural-env` and `uv pip install --python /path/to/neural-env/bin/python -r requirements-neural.txt`. Check out upstream TripoSR at commit `107cefdc244c39106fa830359024f6a2f1c78871`. Download `config.yaml` and `model.ckpt` from the public `stabilityai/TripoSR` model at revision `5b521936b01fbe1890f6f9baed0254ab6351c04a`, plus `facebook/dino-vitb16/config.json` saved as `dino-config.json` in the same weights directory.

Configure these absolute local paths in the MCP server environment:

```text
CAVI_TRIPOSR_PYTHON=/path/to/neural-env/bin/python
CAVI_TRIPOSR_SOURCE=/path/to/TripoSR
CAVI_TRIPOSR_WEIGHTS=/path/to/weights
```

Put an image of one isolated object on white or transparency inside the Blender workspace. Call `generate_mesh` with its relative `image` path and a new `.glb` output `path`. Generation runs offline on CPU with four threads, chunked field queries and a 180-second timeout. Resolution is bounded to 64–192; input images are at most 16 MiB and 4096 pixels per side. Outputs are published without replacing existing files. The returned counts and input SHA-256 identify the generated artifact. Generation creates a GLB file without changing the open scene.


## Shared application ownership

Before editing, call `session_control` with `action="inspect"`, then claim the
returned `project_id` with `action="claim"`, an `owner` label, and that exact
`expected_project`. Claim returns a private `lease_id`; pass it on application
mutations. Read-only inspection remains available without ownership.

Claims last 30–3600 seconds, default 600. Renew with `action="renew"` and release
with `action="release"`, both supplying the same `lease_id`. Release and expiry
never save, close, or discard a project. Conflicting claims and missing, foreign,
expired, or project-mismatched edit tokens are refused. An owned operation holds
its exclusive section until it finishes. A successful owned save or project
transition updates the claim's binding.

Claims coordinate participating MCP clients, not direct human edits or arbitrary
scripts. Upgrade every participating client. Keep lease IDs out of asset receipts
and handoff documents; a new agent inspects and claims its own session.

Blender also needs the upgraded bridge loaded. Preserve the scene before
reopening its dedicated application session. New MCP edits use an owned-edit
protocol envelope that older bridges reject. Listener restart does not reload
bridge code and requires the current edit lease.

## Validation

```sh
uv run --locked python -m unittest discover -s tests
uv run --locked ruff check .
blender --background --factory-startup --python-exit-code 1 --python tests/blender_smoke.py -- /path/to/empty/test-workspace
```

The native smoke creates a disposable scene, edits a mesh, unwraps UVs, exports FBX/GLB, saves a project, and renders a preview. It does not edit a game project.

The additional `tests/blender_organic.py` native check exercises custom topology, evaluated subdivision/remeshing, resource limits, preview isolation and a GLB export/import round trip. Invoke it with the same Blender command and a separate empty workspace.

`tests/blender_import.py` checks typed import on Blender 5.2.3, including transforms,
UVs, vertex-color values, embedded image packing, name reuse, selection preservation,
and rollback after a partial native import. It uses a disposable factory scene and
temporary workspace; no game project is opened.

## MCP evaluation

Install the locked Python and evaluator dependencies, then run the protocol checks:

```sh
uv sync --locked --dev
npm ci
npm run eval:protocol
npm run eval:core -- --blender /path/to/blender
```

The evaluator is pinned to `@cavi-ai/mcp-eval` 0.8.0. The protocol manifest checks discovery size, catalog token budgets, pagination, surface listing, and protocol negotiation. The core manifest adds schema, structured output, repeated reads, and contention checks. The corpus covers all 15 tools through real stdio MCP sessions, including PNG image data, nonempty exports, GLB imports, and edit ownership. The optional model case requires a configured runtime and `--model-image`; ordinary protocol/native runs report model evaluation as not run. No-argument read tools have no tool-specific invalid inputs.

To exercise actual image-to-3D inference, append `--model-image /path/to/original.png` to the native evaluator command. The resulting GLB and report are retained in that run's artifact directory.

Native evaluation starts its own factory scene with a private connection and disposable workspace. It does not connect to an existing Blender session. Reports and application logs remain under `.tmp/evals/`; connection files, scenes, and outputs are ignored by Git. An unavailable executable fails the command rather than producing a native pass. CI runs protocol checks; native checks require Blender and run separately.

These are deterministic protocol and native application evaluations. MCP Eval does not invoke a model; results do not establish model task quality or game integration.
