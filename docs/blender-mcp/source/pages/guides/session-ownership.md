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
6. `action="break"` takes the inspected `expected_project` and ends a lease
   whose owner has not used it for 300 seconds. It returns `previous_owner`.

Claims last 30–3600 seconds and default to 600. Inspection reports
`idle_seconds` since the owner last used the lease.

## Guarantees

- Read-only inspection remains available without ownership.
- Conflicting claims, missing, foreign, expired or project-mismatched tokens are
  refused.
- An owned operation holds its exclusive section until it finishes.
- A successful owned save or project transition updates the claim's binding.
- Release, break and expiry never save, close or discard a project.
- A lease in use, or used within the last 300 seconds, cannot be broken.

The lease token is private. Keep it out of asset receipts and handoff documents.
A new agent inspects and claims its own session.

## Upgrade all clients

New edits use an owned-edit protocol envelope that older bridges reject. Upgrade
every participating client and reload the bridge before editing. Listener
restart does not reload bridge code and itself requires the current edit lease.

## Related

- [Run a dedicated session](runtime-and-headless.md)
- [Security model](../security/model.md)

## Native failure outcomes

Weight/morph transfer, rig baking and retargeting identify validation failures
that finish before editing application data. These arrive with MCP error
`outcome: rejected`. They do not authorize an automatic retry: `retry_safe`
remains false. Correct the reported inputs or state before a new attempt.

Errors after editing begins, transport failures and responses without explicit
rejection evidence remain `outcome: unknown`. Inspect application state and
retained outputs before another mutation. Error-message wording alone does not
establish whether an operation changed the scene. Older bridges without native
outcome metadata retain the conservative unknown classification.
