# CLI

Running `cavi-blender-mcp` without arguments serves MCP over stdio.

```bash
cavi-blender-mcp runtime start [--project PATH] [--background]
cavi-blender-mcp runtime status
cavi-blender-mcp runtime restart --lease-id LEASE
```

| Command | Result |
| --- | --- |
| `runtime start` | Reuses a connected session or launches Blender with the packaged bridge |
| `runtime start --project PATH` | Opens an existing workspace-relative `.blend` in the new session |
| `runtime start --background` | Starts headless Blender |
| `runtime status` | Reports connection, pid, generation, version, file, workspace, object count, dirty state and background mode |
| `runtime restart --lease-id LEASE` | Replaces the bridge listener and credentials without restarting Blender |

`--project` and `--background` apply only to `start`. Commands print JSON and
exit nonzero on failure.

`start` refuses to replace a different connected project. It starts only when
the previous connection is missing or refused; timeouts leave the existing
session untouched.

`restart` requires the current edit lease. It preserves the Blender process,
open scene, unsaved edits and selection. It does not reload Python source or
refresh an MCP client's cached tool catalog.

## Environment

| Variable | Purpose |
| --- | --- |
| `CAVI_BLENDER_BIN` | Blender executable for `runtime start` |
| `CAVI_BLENDER_CONNECTION` | Private connection file |
| `CAVI_BLENDER_WORKSPACE` | Workspace for saves, exports, previews and imports |

See [Configuration](configuration.md).
