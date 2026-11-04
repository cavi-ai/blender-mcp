# Rig and animate

`rig_edit` creates armatures, binds skins, repairs weights and authors actions.
Every call needs a `lease_id` and an OBJECT-mode session.

## Actions

| Action | Use |
| --- | --- |
| `create` | New armature from 1–128 `bones` and an optional `location` |
| `bind` | Automatic weights from `name` armature to 1–16 `names` meshes |
| `weights` | Clean, limit and normalize weights on one skinned mesh |
| `assign_weights` | Set exact deform-bone weights on declared vertices |
| `constraint` | Add IK with pole targets, or local/pose/world rotation limits |
| `remove_constraint` | Remove one named bone constraint |
| `bake` | Create a separate rig and optional skin copies with evaluated transform keys |
| `pose` | Apply bounded pose transforms, optionally resetting first |
| `keyframe` | Create a new action from 1–32 keyframes |
| `clear_pose` | Reset every pose bone, optionally at a frame |
| `retarget` | Bake a source armature action onto the target rig |
| `set_action` | Assign an existing action, or clear the active action |
| `rename_action` | Rename an action |
| `delete_action` | Delete an unreferenced action |
| `nla_push` | Move an action into an NLA track/strip |
| `nla_remove` | Remove one strip, one track, or every track |

## Bones

Bone specifications take `name`, `head`, `tail`, `parent`, `connect`, `deform`
and `roll_degrees`.

Armatures require unique names, nonzero lengths, acyclic parents, and connected
bones that meet their parent tail. Bone names are limited to 63 UTF-8 bytes and
armatures to 128 bones.

## Binding and weights

Automatic binding requires 1–16 single-user meshes without modifiers or shape
keys, at most 50,000 vertices and 64 bones. Binding snapshots mesh data and
restores it on failure.

`weights` affects deform-bone groups only. It is bounded to 100,000 vertices,
512 groups and one million assignments. `max_influences` is 1–32,
`clean_threshold` is 0–1 and `normalize` controls normalization.

## Posing and actions

`pose` applies `rotation_degrees`, `location` and `scale` to named bones. Manual
pose edits are not keyed, and an active action re-evaluates on frame changes.

`keyframe` writes a new action with `action_name`. Frames must be strictly
increasing. Each action is limited to 32 frames, 128 poses per frame and 2,048
poses total. Failure removes the new action and restores the previous action and
pose.

## Clip management

`inspect_rig` lists every action with an object slot in `actions`, in addition
to active and NLA-linked `clips`.

`set_action` assigns `action_name` to the rig; omit it to clear the active
action. `rename_action` changes the action name and refuses collisions.
`delete_action` removes only actions with no active, NLA or other users; clear
references first.

`nla_push` places `action_name`, or the active action, into `track_name` and
`strip_name` at `start_frame`. Strips in one track must not overlap. After a
push the active action is cleared and the clip stays available for export.
`nla_remove` removes a named strip, a whole track, or every track when
`track_name` is omitted.

## Animation QA

`inspect_rig` can sample a clip. Set `action` to a clip name, or omit it to use
the active action, and pass `checks`:

- `root_motion` reports root-bone displacement, horizontal and vertical travel,
  maximum travel and whether the clip loops.
- `loop` compares first and last bone matrices for translation, rotation and
  scale.
- `deformation` reports evaluated mesh bounds, maximum dimensions, dimension
  ratio, centroid movement and non-finite vertices.

`samples` is 2–32 and defaults to 8. The call restores the previous action,
action slot and frame. Deformation sampling is bounded to two million vertex
samples. Foot sliding and engine import quality remain unchecked.

## Retarget

`retarget` bakes a source armature action onto a target armature by world-space
bone transfer. It takes the target `name`, `source` armature, `source_action`,
new `action_name` and optional `mapping` and `samples`.

Without `mapping`, bones with matching names are used. With a mapping, each
source bone maps to one target bone, target bones are used at most once, and
every named bone must exist.

By default every whole source frame is keyed, up to 1,000 frames. `samples`
selects 2–256 evenly spaced frames instead. Armatures are limited to 512 bones,
mappings to 128 pairs and the result to 100,000 keyframes. The result reports
mapped and unmapped bones.

## Verify

Run `inspect_rig` after binding, repair, retargeting or animation. It reports
hierarchy, all object actions, active/NLA clips, slots and weight quality without
changing pose or action.

## Related

- [Inspect a scene](scene-inspection.md)
- [Import and export assets](asset-import-export.md)
- [Limits and boundaries](../reference/limits.md)


## IK and joint limits

`constraint` takes a typed `constraint` object. IK targets may be objects or
bones, including a pole bone on the same rig. A target that depends on the
constrained chain is refused. Names are unique per bone.

```json
{"action":"constraint","name":"CharacterRig","constraint":{"type":"IK","name":"Foot IK","bone":"Shin.L","target":"CharacterRig","subtarget":"FootControl.L","pole_target":"CharacterRig","pole_subtarget":"KneeControl.L","pole_angle_degrees":90,"chain_count":2,"use_stretch":false},"lease_id":"<lease>"}
```

`LIMIT_ROTATION` takes `minimum_degrees`, `maximum_degrees`, `axes` and
`owner_space`. `remove_constraint` takes `bone` and `constraint_name`.
`inspect_rig` reports each bone's constraints, target/pole bindings and limits.

## Exact skin weights

`assign_weights` takes `vertex_weights=[{"vertex":42,"weights":{"Thigh.L":0.75,"Shin.L":0.25}}]`.
Indices must exist and must not repeat. Bone names must belong to the skin's
bound armature and deform the mesh. By default, `replace=true` replaces deform
weights on just those vertices and preserves other vertex groups and vertices.
`replace=false` merges assignments; explicit zero removes a contribution.
`normalize=false` preserves requested values; explicit true normalizes the result.
Invalid assignments are rejected before edits, and native failures restore the
previous affected weights. Inspect the result's normalization and influence counts.

## Bake an independent export rig

`bake` takes `new_name`, `action_name`, `start_frame`, `end_frame`, optional
`frame_step` (default 1), and optional `names` of bound skins to copy. It samples
current evaluated motion, including IK and NLA, into quaternion transform keys
on a separate rig without constraints. The source rig, action and constraints
remain editable. Each skin copy receives its own mesh data and binds to the new
rig. Source and copy names are returned in `skins`.

It checks evaluated bone matrices at every declared sample and restores the
original frame. Dense keys use linear interpolation; larger steps require their
own between-sample motion review. The budget is 4096 samples and one million
bone poses per call. Object shear that transform keys cannot preserve is refused.
It also keys evaluated relative shape weights or absolute shape evaluation time
on independent shape data. Source drivers remain on the editable source.
Simulation and engine import behavior need separate validation. Save the source `.blend`, then
export the returned skin names with `asset_io animations=true`; the exporter includes
their bound armature.

Use `compare_rig_motion` with an explicit metre tolerance to compare evaluated
skins and bone heads, including times between bake keys. A bone-matrix pass alone
can miss skin-weight or shape deformation errors. Export clean baked copies with
`asset_io animations=true baked_animation=true`; FBX accepts an explicit
`animation_sample_step`, and GLB retains authored subframe keys. After reimport,
compare with `vertex_match=point_set` and the measured active-clip frame offset.
See the [tool reference](../reference/tools.md#compare_rig_motion).

## Transfer skin weights to clothing or new topology

`rig_edit transfer_weights` interpolates a bound source skin's deform weights
onto a new independent copy of a target mesh. Align their base meshes in rest
space first; projection uses the current object transforms and base triangles,
not the animated or modifier-evaluated surface. It does not fit a garment.

```json
{"action":"transfer_weights","name":"Coat","source":"Body","new_name":"CoatSkin","max_distance_m":0.02,"max_discarded_weight":0.005,"max_influences":4,"lease_id":"<lease>"}
```

These are example quality budgets; declare them for the asset. The tool uses
[nearest-triangle queries](https://docs.blender.org/api/current/mathutils.bvhtree.html)
and barycentric weight interpolation. It keeps the strongest declared number
of influences and normalizes them. Excess distance or discarded weight rejects
the transfer before edits. The receipt reports both observed maxima.

Source and target remain unchanged. The copy preserves target mesh attributes,
UVs, materials, shape data and non-deform groups. It follows the source mesh's
object motion, replaces its copied armature binding, and binds to the source rig.
Copied object animation and constraints are cleared; other mesh modifiers remain.
The tool transfers bone weights, not source modifier masks or shape animations.

Limits match bounded weight editing: 100,000 vertices per mesh, 200,000 source
triangles and one million source/target deform assignments. Degenerate source
triangles are ignored and counted. Inspect shoulders, hips, fingers and nearby
limbs: nearest geometry does not infer anatomical correspondence or cloth
collision. Continue with sampled bake/export comparisons and engine review.
