# Security model

Blender MCP is local-first. It assumes the MCP client and the Blender process run
on the same trusted machine and that scene contents are not hostile.

## Transport

- The bridge listens on IPv4 `127.0.0.1` on an ephemeral port. It opens no
  external interface.
- Every request carries a random bearer token. Requests without it receive HTTP
  403.
- The connection file contains the port, token and Blender pid. It is created
  privately and the server refuses files owned by another user or readable by
  other users.
- A connection file whose pid is no longer alive is treated as offline and
  removed.

A process that can read the connection file can issue bridge requests. Protect
the file and use only trusted local clients.

## Filesystem

- Saves, exports, previews, baked maps and generated assets must resolve inside
  the configured workspace, including through symbolic links.
- Output files are reserved exclusively before Blender writes them. Existing
  files are never overwritten.
- Imports must resolve inside the workspace. Sources are copied to a private
  temporary file and their SHA-256 is checked before Blender reads them.
- Imported textures must be packed or resolve inside the workspace, depending on
  the format.
- There is no arbitrary Python tool.

## Mutations

- Every mutation requires a claimed edit lease tied to the current project
  identity.
- A successful owned save or project transition updates the lease binding.
- Failed operations restore scene state where the feature supports rollback.
- A timeout is reported as an uncertain outcome. The server never retries a
  mutation automatically.

## Network and models

- The server makes no network requests.
- The optional image-to-3D worker runs offline with local weights.
- No telemetry is collected.
- No vendor presets, samples, artwork or product masters are included.

## Reporting

Report vulnerabilities as described in [SECURITY.md](https://github.com/cavi-ai/blender-mcp/blob/main/SECURITY.md).
