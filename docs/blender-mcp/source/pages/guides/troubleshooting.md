# Troubleshooting

Start with a direct status check:

```bash
cavi-blender-mcp runtime status
```

`connected: false` includes a `reason`. Do not retry a mutation until you know
whether it executed.

## The bridge is not running

`Blender bridge is not running; start Blender with the bridge` means no private
connection file was found.

- Start Blender with `scripts/start_bridge.py`, or run
  `cavi-blender-mcp runtime start`.
- Confirm the MCP server and Blender use the same `CAVI_BLENDER_CONNECTION`.
- If a stale pid was found, the connection file is removed automatically.

## Connection failed or outcome is unknown

`Bridge connection failed; outcome may be unknown` covers refused sockets,
timeouts and protocol-level failures. The request may or may not have reached
Blender. Inspect the scene before resubmitting.

`Bridge HTTP 503` means the bridge queue was full and the request was not
executed. `Bridge HTTP 504` means the request was not started in time and was
not executed.

`Timed out; inspect the scene before retrying` means the request started but did
not finish in time. The outcome is uncertain.

## Connection file is not private

The server refuses a connection file that is not owned by the current user or is
readable by other users. Fix the file mode or remove the file and restart the
bridge. The bridge creates it with private permissions.

## Another bridge owns the connection

Another live Blender bridge answered on the configured connection. Choose a
different `CAVI_BLENDER_CONNECTION` for the new session, or stop the other
bridge.

## An operation is refused before it runs

Common causes:

- The scene is not in Object Mode.
- Mesh data is shared. Make it single-user in Blender.
- The mesh has modifiers or shape keys; apply them first.
- The object is hidden or not in the active view layer.
- A parameter does not belong to the selected action.
- A name already exists.
- A budget in the [limits reference](../reference/limits.md) was exceeded.

These refusals happen before the requested change, so the scene is unchanged.

## Output path is refused

Saves, exports, previews and baked images must stay inside the workspace,
including through symbolic links. The parent directory must already exist, and
existing files are never overwritten.

Check `scene_info.workspace` and set `CAVI_BLENDER_WORKSPACE` in both Blender and
the MCP server if it is not the directory you expect.

## Lease errors

`A valid lease_id is required` means the call needs a claim.
`The edit lease expired` means the lease must be renewed or claimed again.
`The project changed` means the open file, scene or project identity changed.
Inspect and claim again.

## Import is refused

Imports are bounded and preflighted:

- The file must be inside the workspace and at most 64 MiB.
- The asset name must be new and at most 58 UTF-8 bytes.
- External textures, cameras, lights, unsupported shape keys or animation are
  refused according to the format table in
  [Import and export assets](asset-import-export.md).
- A changed source file is refused after preflight.

## Image-to-3D is unavailable

`Configure CAVI_TRIPOSR_*` means the worker environment, source or weights path
is missing or not absolute. See
[Generate a mesh locally](local-generation.md).

## Related

- [Run a dedicated session](runtime-and-headless.md)
- [Security model](../security/model.md)
- [Limits and boundaries](../reference/limits.md)
