"""Run with Blender --background --factory-startup --python-exit-code 1 --python tests/blender_rigify.py."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name)
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "rigify-fixture", "expected_project": state["project_id"]})["lease_id"]


def call(operation, **params):
    return bridge.dispatch(operation, {**params, "lease_id": lease})


def refused(operation, message, **params):
    before = set(bpy.data.objects)
    try:
        call(operation, **params)
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")
    assert set(bpy.data.objects) == before, f"{operation} left objects behind"


def usd_safe(name):
    return name.replace("-", "_").replace(".", "_")


def reimported(path):
    """USD-safe bone names, DEF-spine travel and clip frames of an exported rig, imported and removed."""
    before = set(bpy.data.objects)
    importer = {".fbx": bpy.ops.import_scene.fbx, ".glb": bpy.ops.import_scene.gltf,
                ".usdc": bpy.ops.wm.usd_import}[Path(path).suffix]
    importer(filepath=str(bridge._workspace / path))
    try:
        armatures = [item for item in set(bpy.data.objects) - before if item.type == "ARMATURE"]
        assert len(armatures) == 1, armatures
        bones = {usd_safe(bone.name): bone.name for bone in armatures[0].data.bones}
        names = set(bones)
        assert "DEF_spine" in names, (path, sorted(names))
        clip = armatures[0].animation_data.action
        assert clip is not None, path
        spine = []
        for frame in clip.frame_range:
            bpy.context.scene.frame_set(int(frame))
            spine.append(armatures[0].matrix_world @ armatures[0].pose.bones[bones["DEF_spine"]].head)
        return names, (spine[1] - spine[0]).length, tuple(clip.frame_range)
    finally:
        for item in set(bpy.data.objects) - before:
            bpy.data.objects.remove(item, do_unlink=True)


def bone_bounds(rig):
    points = [rig.matrix_world @ point for bone in rig.data.bones
              for point in (bone.head_local, bone.tail_local)]
    return [min(p[i] for p in points) for i in range(3)], [max(p[i] for p in points) for i in range(3)]


try:
    bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=1.7, location=(1, 2, 0.85))
    body = bpy.context.object
    body.name = body.data.name = "Body"

    meta = call("add_metarig", name="BodyMeta", template="basic_human", source="Body")
    metarig = bpy.data.objects["BodyMeta"]
    assert meta["name"] == "BodyMeta" and meta["bone_count"] == len(metarig.data.bones) > 20
    assert {bone["name"] for bone in meta["bones"]} >= {"spine", "thigh.L", "upper_arm.R"}
    low, high = bone_bounds(metarig)
    assert abs(high[2] - low[2] - 1.7) < 1e-3 and abs(low[2]) < 1e-3, (low, high)
    assert abs((low[0] + high[0]) / 2 - 1) < 1e-3, (low, high)
    assert list(metarig.scale) == [1, 1, 1]

    refused("add_metarig", "unique", name="BodyMeta", template="basic_human")
    refused("add_metarig", "template", name="Other", template="dragon")
    refused("add_metarig", "location or source", name="Other", template="human",
            source="Body", location=[0, 0, 0])
    refused("generate_rigify", "unique", name="BodyMeta", new_name="Body")
    refused("generate_rigify", "Rigify metarig", name="Body", new_name="BodyRig")

    rig = call("generate_rigify", name="BodyMeta", new_name="BodyRig")
    generated = bpy.data.objects["BodyRig"]
    assert rig["name"] == "BodyRig" and generated.type == "ARMATURE"
    assert rig["bone_count"] == len(generated.data.bones)
    assert rig["deform_bones"] == sorted(b.name for b in generated.data.bones if b.use_deform)
    assert rig["deform_bones"] and all(name.startswith("DEF-") for name in rig["deform_bones"])
    assert rig["source"] == "BodyMeta"
    assert "BodyRig" in bpy.context.scene.objects

    bound = call("bind_skin", name="BodyRig", names=["Body"])
    assert bound["bindings"] == 1, bound
    assert any(modifier.type == "ARMATURE" and modifier.object == generated
               for modifier in body.modifiers)
    assert {group.name for group in body.vertex_groups} <= set(rig["deform_bones"])

    posed = call("pose_rig", name="BodyRig", poses=[{"bone": "torso", "location": [0, 0, 0.1]}])
    assert posed["name"] == "BodyRig"
    assert list(generated.pose.bones["torso"].location) == [0, 0, 0.1] or \
        abs(generated.pose.bones["torso"].location.z - 0.1) < 1e-6
    call("clear_pose", name="BodyRig")
    exported = call("export_asset", names=["Body"], path="body.fbx")
    assert exported["bytes"] > 0 and (bridge._workspace / "body.fbx").is_file()

    call("keyframe_rig", name="BodyRig", action_name="Bob", keyframes=[
        {"frame": 1, "poses": [{"bone": "torso", "location": [0, 0, 0]}]},
        {"frame": 9, "poses": [{"bone": "torso", "location": [0, 0, 0.1]}]}])
    for path in ("bob.fbx", "bob.glb"):
        animated = call("export_asset", names=["Body"], path=path, animations=True)
        assert animated["armatures"] == ["BodyRig"] and animated["skinned_meshes"] == ["Body"]
        assert [clip["name"] for clip in animated["animations"]] == ["Bob"], animated
    bones, travel, frames = reimported("bob.fbx")
    assert len(bones) == rig["bone_count"] and frames == (1, 9), (len(bones), frames)
    assert abs(travel - 0.1) < 1e-3, travel

    refused("export_asset", "animations", names=["Body"], path="static.fbx", deform_only=True)
    lean = {}
    for path in ("lean.fbx", "lean.glb", "lean.usdc"):
        exported = call("export_asset", names=["Body"], path=path, animations=True, deform_only=True)
        assert exported["armatures"] == ["BodyRig"], exported
        bones, travel, _ = reimported(path)
        assert {usd_safe(name) for name in rig["deform_bones"]} <= bones, (path, sorted(bones))
        assert len(bones) < rig["bone_count"], (path, len(bones))
        assert abs(travel - 0.1) < 1e-3, (path, travel)
        lean[path] = len(bones)

    full = call("add_metarig", name="FullMeta", template="human", location=[3, 0, 0])
    assert full["bone_count"] > 128 and list(bpy.data.objects["FullMeta"].location) == [3, 0, 0]
    edited = call("edit_armature", name="FullMeta", names=["breast.L"])
    assert edited["bone_count"] == full["bone_count"] - 1, edited

    print(json.dumps({"metarig_bones": meta["bone_count"], "rig_bones": rig["bone_count"],
                      "deform_bones": len(rig["deform_bones"]), "deform_only_export": lean}))
finally:
    folder.cleanup()
