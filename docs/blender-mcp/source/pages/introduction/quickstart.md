# Quickstart

## 1. Inspect before editing

Call `scene_info`. It returns the Blender version, file, workspace, collection
tree and a page of objects. Use `name` to inspect one object, or `limit` and
`offset` to page through the scene.

```json
{"name": "Cube"}
```

Use exact object names from this response in later calls.

## 2. Claim ownership

Every mutation requires an edit lease. Read-only calls do not.

1. Call `session_control` with `action="inspect"`.
2. Claim the returned `project_id` with `action="claim"`, an `owner` label and
   that exact `expected_project`.
3. Pass the returned `lease_id` on every mutation.

```json
{
  "action": "claim",
  "owner": "asset-agent",
  "expected_project": "<project_id from inspect>",
  "ttl_seconds": 600
}
```

Renew or release with the same `lease_id`. Release and expiry never save,
close or discard a project. See
[Share application ownership](../guides/session-ownership.md).

## 3. Make a bounded change

Create a primitive:

```json
{
  "action": "create_primitive",
  "name": "Crate_01",
  "kind": "cube",
  "lease_id": "<lease_id>"
}
```

Then move it:

```json
{
  "action": "transform",
  "name": "Crate_01",
  "location": [0, 0, 0.5],
  "rotation_degrees": [0, 0, 45],
  "lease_id": "<lease_id>"
}
```

The tool refuses unrelated action parameters before contacting Blender.

## 4. Inspect and preview

Run `inspect_mesh_quality` with `checks=["topology", "lightmap",
"transforms", "materials"]`. Then call `render_preview` with a new workspace
`.png` path. Previews do not need a lease and restore scene state.

## 5. Export

Call `asset_io` with `action="export"`, the exact mesh names and a new
workspace path:

```json
{
  "action": "export",
  "names": ["Crate_01"],
  "path": "exports/crate_01.fbx",
  "axis": "unity",
  "lease_id": "<lease_id>"
}
```

Existing files are refused. The parent directory must already exist.

Continue with [Import and export assets](../guides/asset-import-export.md) or
the full [tools reference](../reference/tools.md).
