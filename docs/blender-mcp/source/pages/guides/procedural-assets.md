# Reuse a procedural asset

Start with an artist-authored Geometry Nodes asset in an owned Blender source.
Inspect the scene and claim its edit lease. `geometry_nodes` edits the exposed
interface; node topology and shared group defaults stay authored inputs.

1. `geometry_nodes` `inspect` with the object `name`. Choose the exact modifier
   and socket identifiers from the response. Display names can repeat; an
   identifier belongs to that graph revision and must be refreshed after edits
   to its interface. Non-value sockets are reported as non-editable.
2. `set_inputs` takes the exact `modifier`, sparse `inputs` and current lease.
   Scalars, vectors, colors, rotations, strings and object/collection/material/image
   references use their socket's native storage and numeric limits. Integers
   require integers. References use `{ "name": "Paint", "id_type": "MATERIAL" }`
   or null; an existing material is selected without editing its source graph.
3. A field input can use `attributes: { "Socket_4": "density_mask" }`. A null
   attribute value returns it to value mode. Editing a fallback value preserves
   an existing attribute mode unless deliberately changed. Attribute existence,
   domain and artistic effect require inspection of the evaluated geometry.
4. Inspect the returned settings and the actual evaluated variant. Changes are
   modifier-local, so another object sharing the node group keeps its values.
   Input values driven by animation are still driven when the frame changes.
5. Save a new editable `.blend`, then `bake_copy` into a unique `new_name`. This
   takes the whole evaluated mesh stack at the current fractional frame, retains
   mesh data layers and material bindings, and creates an independent mesh with
   the same world transform and no modifiers. Review size, triangles and
   `material_triangles`, including unused slots.
6. Apply the destination's UV, LOD, collision and material workflow to the copy.
   Export with `asset_io`, then reimport and compare dimensions, topology counts
   and material usage. Import acceptance and visual quality remain separate checks.

Do not pass display names as socket identifiers or overwrite the source with a
baked mesh. Snapshots capture the mesh component; convert curve/volume components
in the source if required. A graph with unrealized instances must use Realize
Instances for this snapshot path, or retain instances through `asset_io` export
with `preserve_instances`. No instance content is silently dropped by the snapshot.
