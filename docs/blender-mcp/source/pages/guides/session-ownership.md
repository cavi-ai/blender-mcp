# Share application ownership

`session_control` coordinates independent MCP clients that share one Blender
session. Claims coordinate participating clients, not direct human edits or
arbitrary scripts.

## Flow

1. `action="inspect"` returns `project_id`, the current owner and lease state.
2. `action="claim"` takes `owner`, the exact inspected `expected_project` and an
   optional `ttl_seconds`.
3. Pass the returned `lease_id` on every mutation.
4. `action="renew"` extends the lease.
5. `action="release"` ends it.

Claims last 30–3600 seconds and default to 600.

## Guarantees

- Read-only inspection remains available without ownership.
- Conflicting claims, missing, foreign, expired or project-mismatched tokens are
  refused.
- An owned operation holds its exclusive section until it finishes.
- A successful owned save or project transition updates the claim's binding.
- Release and expiry never save, close or discard a project.

The lease token is private. Keep it out of asset receipts and handoff documents.
A new agent inspects and claims its own session.

## Upgrade all clients

New edits use an owned-edit protocol envelope that older bridges reject. Upgrade
every participating client and reload the bridge before editing. Listener
restart does not reload bridge code and itself requires the current edit lease.

## Related

- [Run a dedicated session](runtime-and-headless.md)
- [Security model](../security/model.md)
