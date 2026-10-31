# Rig and animate

`rig_edit` creates armatures, binds skins, repairs weights and authors actions.
Every call needs a `lease_id` and an OBJECT-mode session.

## Actions

| Action | Use |
| --- | --- |
| `create` | New armature from 1–128 `bones` and an optional `location` |
| `bind` | Automatic weights from `name` armature to 1–16 `names` meshes |
| `weights` | Clean, limit and normalize weights on one skinned mesh |
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
