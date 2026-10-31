# Edit objects

`object_edit` creates or changes one object. Every action needs a `lease_id`.
Unrelated action parameters are refused before contacting Blender.

## Actions

| Action | Parameters |
| --- | --- |
| `create_primitive` | `kind` = cube, sphere, cylinder, cone or plane; `location` |
| `create_mesh` | `vertices`, `faces`; zero-based outward winding |
| `transform` | `location`, `rotation_degrees` (XYZ Euler), `scale` |
| `set_color` | `rgba`, `slot` (default 0) |
| `shade` | `smooth` |
| `apply_transforms` | `components` from location, rotation, scale; `make_single_user` |
| `set_origin` | `origin` = bounds_bottom_center, bounds_center, world_origin or point; `location` for point |
| `snap_to_grid` | `grid` |
| `rename` | `new_name`; also renames single-user mesh data |
| `add_socket` | `new_name`, local `location`, `rotation_degrees` |
| `duplicate` | `new_name`, `count`, world `offset`, `linked` |
| `parent` | `new_name` is the parent; preserves world transform |
| `unparent` | no extra parameters; preserves world transform |
| `move_to_collection` | `new_name`, `create` |

## Transforms and origins

`transform` honors the object's rotation mode. `rotation_degrees` is always XYZ
Euler input.

`apply_transforms` bakes the selected components into mesh data. Shared mesh data
needs `make_single_user=true`. Children keep their world transforms.

`set_origin` moves the object origin without moving geometry. `point` takes a
world-space `location`; the other modes use local bounds or world zero.

## Names and hierarchy

`rename` refuses an existing object name. `add_socket` creates an empty named
`SOCKET_<new_name>` at a local offset under the object.

`parent` refuses cycles and preserves the child's world transform. `unparent`
does the same while removing the parent.

## Duplicates and collections

`duplicate` creates `new_name` or `<new_name>_01` through `_NN` for multiple
copies. `linked=true` shares mesh data; the default copies it. Each copy is
offset in world space by its index.

`move_to_collection` moves the object to a named collection. `create=true`
creates the collection when missing.

## Related

- [Prepare meshes](mesh-preparation.md)
- [Materials and UVs](materials-and-uvs.md)
- [Tools reference](../reference/tools.md)
