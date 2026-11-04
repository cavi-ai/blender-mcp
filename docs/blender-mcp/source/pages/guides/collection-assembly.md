# Assemble reusable environment kits

Append a native collection as an instance to place an editable modular kit. Its
objects and procedural graphs remain in one local collection definition, while
placement empties carry each kit's transform.

1. Inspect the owned scene, claim its lease and inspect the workspace `.blend`
   with `asset_library` to obtain collection names and source SHA-256.
2. Append the chosen names with `kind="collections"`, `instance_collections=true`
   and the inspected `expected_sha256`. Use the returned `instances` names;
   `roots` identifies the imported collection definitions. Existing names can
   receive suffixes. Each append imports independent definitions.
3. Use `object_edit` `duplicate` on the returned instance object, then `transform`
   each placement. Duplicated collection instances share their definition even
   when `linked=false`: they have no mesh data to copy. Use `object_edit` `make_unique` with a unique `new_name` to branch the current
   definition, or reappend the library to start from its saved source. Negative nonzero scale supports mirrored placement.
   To edit its source controls, inspect `scene_info` with `name` and
   `definition=true`, then use `geometry_nodes` inspect/set_inputs with the exact
   member name and scene `instance`. See [procedural controls](procedural-assets.md).
4. Save the editable destination `.blend`. For a static engine handoff, call
   `asset_io` `export` with the placement `names`, `assembly=true` and an FBX or
   GLB path. Optional `axis` selects the existing target preset; `textures=true`
   writes FBX image sidecars. GLB embeds its supported images.
5. Review the receipt and reimport the export. Check placement counts, triangle
   budgets, material bindings and world geometry, especially nested pivots,
   mirrors and nonuniform scale. Compare appearance in the consuming renderer.

The assembly export captures visible evaluated mesh surfaces at the current
fractional frame, including nested collection instances and evaluated mesh
modifiers. It shares compatible mesh data and bakes shear into temporary copies
when rotation/scale alone cannot represent the placement. The receipt includes
per-placement source names, world matrices, triangles and `shear_baked`, plus
the exported `unique_meshes` count. Source graphs, objects and selection remain
editable; temporary IDs are removed on success or exporter failure.

`non_mesh_instance_counts` and `empty_mesh_instances` report components outside
the mesh handoff. Inspect these before accepting an export. This mode produces
static surfaces, not animated rigs, lights, cameras, volumes or an engine prefab
hierarchy. Use the rig/animation export path for animated characters. No LOD or
collision semantics are inferred from collection membership.

## Branch the currently edited kit

Select the placement to vary and call `object_edit` with `action="make_unique"`,
its existing `name`, a unique collection `new_name`, and the current lease. The
object keeps its name and placement transform. Its new definition retains current
procedural overrides, nested collections, materials and native dependencies.
Other placements continue to reference the original definition.

The response's `source_collection` and `instance_collection` identify the branch.
Use `items` to map current source IDs to their copied names, or inspect the new
`scene_info` definition page. Names can receive native suffixes. `created_counts`
covers copied dependencies; `items_truncated` qualifies the mapping inventory.

Packed maps retain their stored bytes. External texture files retain their file
bindings and color spaces; they remain shared files. Use new texture outputs and
bind them through the material workflow when the variant needs independent file
contents. Forking a definition does not duplicate those external files.

Save the editable consumer, change the new controls, and compare the evaluated
source and variant before export. The private native snapshot is removed after
copying. An operation failure restores the original definition and removes newly
created IDs. After an uncertain transport result, inspect the selected object's
current definition before attempting another mutation.

Use [material variants](materials-and-uvs.md) for internal slot assignment and
per-object finishes on shared mesh geometry. Inspect slot names and link modes
from the definition page before binding maps.
