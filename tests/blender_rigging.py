"""Native armature creation, automatic binding and weight repair checks."""

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
    "action": "claim", "owner": "rigging-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch("owned_edit", {"operation": operation,
                                          "params": {**params, "lease_id": lease}})


def refused(operation, message, **params):
    try:
        edit(operation, **params)
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


try:
    created = edit("create_armature", name="TestRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0]},
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0, 1],
         "connect": True, "deform": True},
    ])
    rig = bpy.data.objects["TestRig"]
    assert rig.type == "ARMATURE" and created["bone_count"] == 2, created
    assert [bone["name"] for bone in created["bones"]] == ["Root", "Spine"]
    assert created["bones"][1]["parent"] == "Root" and created["bones"][1]["connect"]
    assert rig.data.bones["Spine"].use_connect
    assert rig.data.bones["Root"].use_deform

    bpy.ops.mesh.primitive_uv_sphere_add(location=(0, 0, 0))
    mesh = bpy.context.object
    mesh.name = mesh.data.name = "BindMesh"
    bound = edit("bind_skin", name="TestRig", names=["BindMesh"])
    assert bound["bindings"] == 1, bound
    assert mesh.parent == rig
    modifiers = [item for item in mesh.modifiers if item.type == "ARMATURE"]
    assert len(modifiers) == 1 and modifiers[0].object == rig
    assert {"Root", "Spine"} <= {group.name for group in mesh.vertex_groups}
    assert bound["meshes"][0]["weights"]["sum_max"] is not None

    for name in ("Root", "Spine"):
        group = mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
        group.add(list(range(len(mesh.data.vertices))), 0.6, "REPLACE")
    before = bridge.dispatch("inspect_rig", {
        "armature": "TestRig", "meshes": ["BindMesh"], "max_influences": 1})
    before_weights = before["meshes"][0]["weights"]
    assert before_weights["over_limit_vertices"] > 0, before_weights
    assert before_weights["unnormalized_vertices"] > 0, before_weights
    repaired = edit("repair_weights", name="BindMesh", max_influences=1,
                    clean_threshold=0.0001, normalize=True)
    after = bridge.dispatch("inspect_rig", {
        "armature": "TestRig", "meshes": ["BindMesh"], "max_influences": 1})
    after_weights = after["meshes"][0]["weights"]
    assert after_weights["over_limit_vertices"] == 0, after_weights
    assert after_weights["unnormalized_vertices"] == 0, after_weights
    assert after_weights["unweighted_vertices"] == 0, after_weights
    assert after_weights["max_influences"] == 1, after_weights
    assert repaired["before"]["over_limit_vertices"] > 0

    refused("bind_skin", "no modifiers", name="TestRig", names=["BindMesh"])
    assert len([item for item in mesh.modifiers if item.type == "ARMATURE"]) == 1
    shape = bpy.data.objects.new("ShapeMesh", bpy.data.meshes.new("ShapeMesh"))
    bpy.context.scene.collection.objects.link(shape)
    shape.shape_key_add(name="Basis")
    refused("bind_skin", "shape-keyed", name="TestRig", names=["ShapeMesh"])
    assert not shape.modifiers

    bpy.ops.mesh.primitive_cube_add(location=(5, 0, 0))
    unbound = bpy.context.object
    unbound.name = "UnboundMesh"
    refused("repair_weights", "armature", name="UnboundMesh")

    def ends(bone):
        return [tuple(round(v, 5) for v in point) for point in (bone.head_local, bone.tail_local)]

    # Move a connected chain, add bones, then remove a middle bone.
    edited = edit("edit_armature", name="TestRig", bones=[
        {"name": "Spine", "parent": "Root", "head": [0, 0, 0], "tail": [0, 0.5, 1.5], "connect": True},
        {"name": "Neck", "parent": "Spine", "head": [0, 0.5, 1.5], "tail": [0, 0.5, 1.8],
         "connect": True},
        {"name": "Skull", "parent": "Neck", "head": [0, 0.5, 1.8], "tail": [0, 0.5, 2.2],
         "connect": True},
    ])
    assert edited["bone_count"] == 4, edited
    assert ends(rig.data.bones["Spine"]) == [(0, 0, 0), (0, 0.5, 1.5)]
    assert rig.data.bones["Skull"].parent.name == "Neck"
    trimmed = edit("edit_armature", name="TestRig", names=["Neck"])
    assert trimmed["bone_count"] == 3 and trimmed["removed"] == ["Neck"], trimmed
    skull = rig.data.bones["Skull"]
    assert skull.parent.name == "Spine" and not skull.use_connect
    assert ends(skull) == [(0, 0.5, 1.8), (0, 0.5, 2.2)]
    refused("edit_armature", "skin weights", name="TestRig", names=["Spine"])
    refused("edit_armature", "cycle", name="TestRig", bones=[
        {"name": "Root", "parent": "Skull", "head": [0, 0, -1], "tail": [0, 0, 0]}])
    refused("edit_armature", "parent tail", name="TestRig", bones=[
        {"name": "Root", "head": [0, 0, -1], "tail": [0, 0, 0.5]}])
    refused("edit_armature", "missing parent", name="TestRig", bones=[
        {"name": "Tail", "parent": "Neck", "head": [0, 0, 0], "tail": [0, -1, 0]}])
    assert sorted(rig.data.bones.keys()) == ["Root", "Skull", "Spine"]
    assert ends(rig.data.bones["Root"]) == [(0, 0, -1), (0, 0, 0)]

    for bones, message in [
        ([{"name": "A", "head": [0, 0, 0], "tail": [0, 0, 1]},
          {"name": "A", "head": [0, 0, 1], "tail": [0, 0, 2]}], "repeated"),
        ([{"name": "A", "parent": "B", "head": [0, 0, 0], "tail": [0, 0, 1]},
          {"name": "B", "parent": "A", "head": [0, 0, 1], "tail": [0, 0, 2]}], "cycle"),
        ([{"name": "A", "parent": "Missing", "head": [0, 0, 0], "tail": [0, 0, 1]}],
         "missing parent"),
        ([{"name": "A", "head": [0, 0, 0], "tail": [0, 0, 1]},
          {"name": "B", "parent": "A", "connect": True,
           "head": [0, 0, 2], "tail": [0, 0, 3]}], "parent tail"),
        ([{"name": "A", "parent": "A", "head": [0, 0, 0], "tail": [0, 0, 1]}],
         "parent itself"),
    ]:
        refused("create_armature", message, name="BadRig", bones=bones)
        assert "BadRig" not in bpy.data.objects

    many = [{"name": f"B{index}", "head": [0, 0, index], "tail": [0, 0, index + 1]}
            for index in range(129)]
    refused("create_armature", "1 to 128", name="TooManyBones", bones=many)

    try:
        bridge.dispatch("create_armature", {"name": "UnownedRig", "bones": [
            {"name": "Root", "head": [0, 0, 0], "tail": [0, 0, 1]}]})
        raise AssertionError("Unowned armature creation succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)

    print(json.dumps({
        "created_bones": created["bone_count"],
        "bound_groups": sorted(group.name for group in mesh.vertex_groups),
        "weights_before": [before_weights["over_limit_vertices"],
                           before_weights["unnormalized_vertices"]],
        "weights_after": [after_weights["over_limit_vertices"],
                          after_weights["unnormalized_vertices"]],
        "rollback_cases": 5,
    }))
finally:
    folder.cleanup()
