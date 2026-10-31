# Security

## Reporting a vulnerability

Report vulnerabilities privately through GitHub's "Report a vulnerability" form
on the repository's Security tab. Do not open a public issue.

Supported releases are the latest tagged release on `main`. Before 1.0, older
releases are not patched.

## Scope

- The bridge binds only to IPv4 loopback on an ephemeral port. It opens no
  external interface.
- The connection file is private to the current user and contains a random
  bearer token. Requests without that token are rejected.
- Every mutation requires a claimed edit lease and a matching project identity.
  Read-only inspection remains available without ownership.
- Saves, exports, previews, imports and generated assets are confined to the
  configured workspace, including through symbolic links. Existing outputs are
  never overwritten.
- There is no arbitrary Python tool, telemetry, external asset download or
  remote inference. The optional image-to-3D worker runs offline with local
  weights.
- The bridge grants full scene access to any process that can read the
  connection file. Use it only with trusted local MCP clients.

Report anything that bypasses these boundaries.
