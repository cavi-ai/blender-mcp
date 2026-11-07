# Run a dedicated session

The CLI starts, inspects and restarts a dedicated Blender bridge session.

```bash
cavi-blender-mcp runtime start
cavi-blender-mcp runtime start --project working-copy.blend
cavi-blender-mcp runtime start --background
cavi-blender-mcp runtime status
cavi-blender-mcp runtime restart --lease-id <current-lease>
```

Commands print JSON and exit nonzero on failure.

## Start

`start` reuses a connected session or launches Blender with factory settings,
embedded script auto-execution disabled and the packaged bridge.

It starts only when the prior connection is missing or refused. Timeouts and
uncertain failures leave existing sessions untouched.

- `--project` selects an existing workspace-relative `.blend`. It refuses to
  replace a different connected project.
- `--background` launches headless Blender. The bridge blocks its main thread on
  the request queue and removes its connection file on SIGTERM.
- `CAVI_BLENDER_BIN` overrides executable discovery. Otherwise the CLI uses
  Blender on `PATH` or the standard macOS installation.

Launch acceptance does not prove readiness. Require a successful status check
before asset operations.

## Supervised launches

A consuming supervisor can set `CAVI_MCP_PROCESS_OWNER` to MCP Core's private
owner configuration. Runtime startup, local reconstruction and nested UV workers
then require the shared [owned-exec registration gate](https://github.com/cavi-ai/mcp-core#owned-execution)
before the native command executes. Missing gate support or invalid registration refuses launch.

Supervised runtime starts require `--background` and refuse to adopt an already
connected bridge. Inspect that runtime's existing ownership before continuing.
The launcher waits for its child's matching owner record before returning, so a
short-lived CLI cannot orphan the child before registration. A missing registration
retires the direct child and fails startup. Core still requires its own matching
acknowledgment before the native command executes.
The supervisor retains responsibility for admission, process identity, deadlines,
memory and cleanup; a launch request alone does not establish these results.

Runtime startup seals the selected Core gate file, its hash and host Python in
`CAVI_MCP_PROCESS_GATE` for Blender's embedded Python. Nested UV workers use this
handoff without importing the host's ABI-specific site-packages. Keep the owner
configuration and handoff scoped to the supervised attempt.

New helper launch sites must use `process_launch.command` with the same child
environment and working directory supplied to the subprocess API. Preserve the
owner through child environments; do not add an unregistered fallback.

## Status and restart

`status` and `restart` control the bridge inside an already running Blender
session. `restart` replaces the local listener and credentials, then checks the
new connection.

It preserves the Blender process, open scene, unsaved edits and selection. A
failed request is never automatically retried.

Restarting the listener does not reload Python source or refresh an MCP client's
cached tool catalog. After installing new tools, restart that client's MCP
connection to discover them.

## Connection files

The bridge writes a private connection file containing the loopback port, bearer
token and Blender pid. A file whose pid is no longer alive is treated as offline
and removed.

`CAVI_BLENDER_CONNECTION` selects the connection file. Separate concurrent
sessions require separate connection files configured in both Blender and the
MCP server.

## Related

- [Troubleshooting](troubleshooting.md)
- [CLI reference](../reference/cli.md)
- [Configuration](../reference/configuration.md)
