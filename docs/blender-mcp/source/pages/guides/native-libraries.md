# Reuse editable Blender assets

Use a workspace `.blend` library to bring native objects, collections, materials
or node groups into the current project. This retains editable dependencies;
exchange-format import and evaluated mesh snapshots serve a different handoff.

1. `asset_library` `inspect` with `path` and the desired `kind`. The catalog is
   paginated and includes exact source names plus a SHA-256. Collections are a
   useful unit for a rig with its skins, or a procedural module with its controls.
2. Claim the current Blender project's lease. Call `append` with the same path
   and kind, exact selected names, inspected `expected_sha256` and lease.
   A stale hash or missing name fails before append.
3. Use the returned `roots` and `items` mappings. Native import events identify
   source IDs even when Blender resolves a collision with `.001` or another
   suffix. Existing local IDs are not reused. Object and collection roots use
   Blender's native linking into the scene; standalone materials and node groups
   receive fake users for retention.
4. Inspect the imported result: `geometry_nodes` for exposed controls,
   `inspect_rig` for bone/skin/clip bindings, and material/image bindings for
   surface assets. Appended custom rigs still require their owning add-ons or
   driver namespaces. A retained action name is not deformation acceptance.
5. Vary the editable asset, then save a new destination `.blend`. Use the existing
   bake, export, reimport and delivery workflows for the final engine asset.

Packed textures retain their stored bytes and include per-file hashes in the
receipt. The source library hash pins their source container. Unpacked image
files must be present in the workspace; their receipts retain paths, hashes and
sizes. No texture conversion or precision reduction is performed during append.

The source file is checked before and after append, and the active project path,
scene, selection and active collection are preserved. On a native or dependency
failure the tool removes newly created IDs and restores the selection. Inspect
the project after a transport failure before another mutation; do not blindly
repeat an uncertain append. Large batches can create many dependencies, so use
the source catalog and project budgets before selecting roots.
