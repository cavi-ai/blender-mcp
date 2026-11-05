# Import and export assets

`asset_io` moves assets in or out of the Blender session. Import, export and save
need a `lease_id`. Generation does not.

## Import

```json
{
  "action": "import",
  "path": "imports/character.glb",
  "name": "Character",
  "lease_id": "<lease_id>"
}
```

The suffix selects the importer: `.glb`, `.fbx`, `.obj`, `.usd`, `.usda` or
`.usdc`.

Imports:

- require an OBJECT-mode session
- require a new, unique asset name
- copy the source to a private temporary file and verify its SHA-256 before
  Blender reads it
- install the result in a collection named after the asset
- remove new datablocks and restore selection on failure

| Format | Supported | Refused |
| --- | --- | --- |
| GLB | Static, skinned, animated, morph targets/shape keys and shape-key animation; embedded PNG/JPEG | Cameras, lights, compressed geometry, external dependencies, cyclic or deep hierarchies |
| FBX | Static, skinned, animated, ASCII or binary | Shape keys, cameras, lights, external textures |
| OBJ | Static mesh and materials | External or missing MTL/textures |
| USD | Static, materials, armatures, skinned meshes | Animation clips, blendshapes, cameras, lights, external texture paths |

Textures must be packed or resolve inside the workspace, depending on the
format. Source files are capped at 64 MiB.

## Export

```json
{
  "action": "export",
  "names": ["Character"],
  "path": "exports/character.fbx",
  "lods": true,
  "collision": true,
  "axis": "unity",
  "lease_id": "<lease_id>"
}
```

Formats are `.fbx`, `.glb`, `.usd`, `.usda` and `.usdc`.

- `lods=true` adds every `<base>_LODn` sibling.
- `collision=true` adds `UCX_`, `UBX_` or `USP_` objects.
- `preserve_instances=true` shares geometry between local, unmodified static FBX
  or USD sources with matching distinct material slots.
- `include_empties=true` adds empty ancestors and empty descendants such as
  sockets.
- `animations=true` applies to FBX, GLB and USD. It includes the armatures of the
  named skinned meshes and exports every linked action. GLB and USD also export
  shape-key actions. It refuses LODs, collision, instances and pair baking.
- `textures=true` applies to FBX and USD. It copies used images into a new
  `<stem>.fbm` directory beside the export and returns a texture receipt. An
  existing sidecar directory is refused. USD writes relative texture paths. GLB
  embeds packed textures.
- GLB and USD exports include shape keys/morph targets and shape-key animation.
  FBX shape-key animation remains out of scope.

### Choose primary texture coordinates

Use `uv_layer` when baked textures target a named atlas that differs from the
authoring shader's default coordinates:

```json
{"action":"export","names":["Hero"],"path":"exports/hero.fbx","uv_layer":"BakeAtlas","lease_id":"<claim-token>"}
```

FBX and GLB receive that map as UV0. USD receives it as the named `st` primvar;
USD primvars do not define an ordinal UV0. The selected map becomes render-active
on temporary mesh data. Other UV coordinates are retained. In USD, an existing
secondary `st` map takes the selected map's former name to avoid a collision.

The `uv_maps` receipt identifies each object, original layer/index and exported
layer mapping. FBX/GLB report `export_index: 0`; USD reports
`export_primvar: st` and a null index. Consume this mapping rather than inferring
the primary coordinates from a USD importer's layer order.

The source mesh, shared-data relationships, material bindings and authoring UV
flags are restored after export, including a failed encoder. Named layers must
exist on every selected render mesh, including requested LODs. Generated collision
meshes do not need the atlas. The option also applies to evaluated collection
assemblies and the existing animated export path. Bake pairs use their source UVs.

This chooses geometry coordinates; it does not translate a procedural material
or attach baked maps automatically. Bind the actual maps in the consuming material
and validate its UV channel and normal-map tangent convention. This option requires
an updated server and bridge; older bridges refuse the distinct export operation
before writing a file.

### Axis presets

| Preset | FBX and USD |
| --- | --- |
| `unity` | Y forward, Z up; FBX scale units; no baked transform |
| `unreal` | X forward, Z up; no FBX scale conversion; no baked transform |
| `godot` | -Z forward, Y up; all FBX scale; baked space transform |

glTF is always +Y up. `axis` is refused for GLB.

### Bake pairs

`bake_pair={"high": [...], "low": [...]}` writes `<stem>_low.fbx` and
`<stem>_high.fbx`. Each base needs exactly one low and one high object. Objects
and single-user meshes are temporarily named `<base>_low` and `<base>_high` for
name-matched baking in tools such as Substance Designer, then restored.

## Save

```json
{"action": "save", "path": "projects/scene.blend", "lease_id": "<lease_id>"}
```

`save` writes a new `.blend` inside the workspace and does not overwrite an
existing file.

## Generate

`action="generate"` runs local image-to-3D inference and writes a new `.glb`. It
does not change the open scene. See
[Generate a mesh locally](local-generation.md) and
[configuration](../reference/configuration.md).

## Related

- [Limits and boundaries](../reference/limits.md)
- [Rig and animate](rigging-and-animation.md)
- [Troubleshooting](troubleshooting.md)
