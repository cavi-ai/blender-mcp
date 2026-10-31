"""Native composition checks: booleans, joins, splits, arrays, hierarchy and rollback."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
bridge._workspace = Path(folder.name).resolve()
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "compose-fixture",
    "expected_project": state["project_id"]})["lease_id"]
results = {}


def edit(op, **params):
    return bridge.dispatch("owned_edit", {"operation": op,
                                          "params": {**params, "lease_id": lease}})


def refused(op, message, **params):
    try:
        edit(op, **params)
    except (ValueError, RuntimeError) as exc:
        assert message in str(exc), exc
    else:
        raise AssertionError(f"{op} accepted {params}")


def tris(value):
    return sum(len(poly.vertices) - 2 for poly in value.data.polygons)


def cube(name, location=(0, 0, 0), scale=(1, 1, 1), material=None):
    edit("create_primitive", name=name, kind="cube", location=location)
    value = bpy.data.objects[name]
    value.scale = scale
    if material:
        edit("assign_material", names=[name], material_name=material,
             base_color=[1, 0, 0, 1])
    bpy.context.view_layer.update()
    return value


def plane(name, location=(0, 0, 0)):
    edit("create_primitive", name=name, kind="plane", location=location)
    value = bpy.data.objects[name]
    bpy.context.view_layer.update()
    return value


try:
    # Boolean union removes the operand and preserves the target.
    union_target = cube("BoolUnion", material="UnionMat")
    union_operand = cube("BoolOperand", location=(.5, 0, 0), material="OperandMat")
    before = tris(union_target) + tris(union_operand)
    union = edit("boolean_mesh", name="BoolUnion", operand="BoolOperand", operation="union")
    assert union["operation"] == "union" and union["operand_kept"] is False, union
    assert "BoolOperand" not in bpy.data.objects
    assert union["triangles"] == tris(union_target) > 12
    assert union["triangles_before"] == before
    assert {slot.material.name for slot in union_target.material_slots if slot.material} >= {
        "UnionMat", "OperandMat"}
    results["boolean_union"] = [before, union["triangles"]]

    # Boolean difference and intersect, including keeping the operand.
    diff_target = cube("BoolDiff")
    diff_operand = cube("BoolDiffOperand", location=(.5, 0, 0))
    difference = edit("boolean_mesh", name="BoolDiff", operand="BoolDiffOperand",
                      operation="difference", solver="fast", keep_operand=True)
    assert difference["operand_kept"] is True and "BoolDiffOperand" in bpy.data.objects
    assert difference["triangles"] > 0
    inter_target = cube("BoolInter")
    inter_operand = cube("BoolInterOperand", location=(.5, 0, 0))
    intersect = edit("boolean_mesh", name="BoolInter", operand="BoolInterOperand",
                     operation="intersect")
    assert intersect["triangles"] > 0
    results["boolean_modes"] = [difference["triangles"], intersect["triangles"]]

    # An empty boolean restores both meshes.
    empty_target = cube("BoolEmpty")
    empty_operand = cube("BoolEmptyOperand")
    empty_before = tris(empty_target)
    refused("boolean_mesh", "no faces", name="BoolEmpty", operand="BoolEmptyOperand",
            operation="difference")
    assert tris(empty_target) == empty_before
    assert "BoolEmptyOperand" in bpy.data.objects
    results["boolean_rollback"] = empty_before

    # Join merges geometry, transforms, UVs and material slots.
    join_target = cube("JoinTarget", material="JoinA")
    join_source = cube("JoinSource", location=(3, 0, 0), material="JoinB")
    joined = edit("join_meshes", name="JoinTarget", names=["JoinSource"])
    assert "JoinSource" not in bpy.data.objects
    assert joined["triangles"] == 24 and tris(join_target) == 24
    assert join_target.data.name == "JoinTarget"
    assert {slot.material.name for slot in join_target.material_slots if slot.material} >= {
        "JoinA", "JoinB"}
    assert len({tuple(round(c, 4) for c in vertex.co) for vertex in join_target.data.vertices}) == 16
    results["join"] = [joined["triangles"], len(join_target.material_slots)]

    # Separate loose parts keeps the source and names the other shells.
    split = edit("separate_mesh", name="JoinTarget", by="loose_parts")
    assert split["count"] == 2, split
    assert all(part["name"] in bpy.context.scene.objects for part in split["parts"])
    assert sum(tris(bpy.data.objects[part["name"]]) for part in split["parts"]) == 24
    other = bpy.data.objects["JoinTarget_part_01"]
    results["separate_loose"] = [part["name"] for part in split["parts"]]

    # Separate by material after joining the shells back together.
    edit("join_meshes", name="JoinTarget", names=[other.name])
    by_material = edit("separate_mesh", name="JoinTarget", by="materials")
    assert by_material["count"] == 2, by_material
    assert all(part["material_index"] is not None for part in by_material["parts"])
    results["separate_materials"] = [part["material_index"] for part in by_material["parts"]]

    # Mirror, array and solidify apply through evaluated geometry.
    mirrored = cube("MirrorTarget", location=(1, 0, 0))
    mirror = edit("mirror_mesh", name="MirrorTarget", symmetry_axis="X",
                  merge_distance=0, clipping=True)
    assert mirror["triangles"] == 24 == tris(mirrored)
    refused("mirror_mesh", "X, Y or Z", name="MirrorTarget", symmetry_axis="W")
    arrayed = cube("ArrayTarget")
    array = edit("array_mesh", name="ArrayTarget", count=3, offset=(2, 0, 0))
    assert array["triangles"] == 36 == tris(arrayed)
    refused("array_mesh", "not be zero", name="ArrayTarget", count=2, offset=(0, 0, 0))
    refused("array_mesh", "from 2 to 1000", name="ArrayTarget", count=1001,
            offset=(1, 0, 0))
    shell = plane("ShellTarget")
    shell_before = tris(shell)
    solid = edit("solidify_mesh", name="ShellTarget", thickness=.1, offset=-1)
    assert solid["triangles"] > shell_before == 2
    results["modifiers"] = [mirror["triangles"], array["triangles"], solid["triangles"]]

    # Duplicate copies transforms, data and names; linked duplicates share data.
    original = cube("DupSource")
    copies = edit("duplicate_object", name="DupSource", new_name="DupCopy", count=2,
                  offset=(2, 0, 0))
    assert copies["objects"] == ["DupCopy_01", "DupCopy_02"]
    assert [tuple(round(c, 4) for c in bpy.data.objects[n].location)
            for n in copies["objects"]] == [(2, 0, 0), (4, 0, 0)]
    assert bpy.data.objects["DupCopy_01"].data is not original.data
    linked = edit("duplicate_object", name="DupSource", new_name="DupLinked", count=1,
                  linked=True)
    assert bpy.data.objects[linked["objects"][0]].data is original.data
    refused("duplicate_object", "unique", name="DupSource", new_name="DupSource")
    refused("duplicate_object", "from 1 to 256", name="DupSource", new_name="TooMany",
            count=257)
    results["duplicate"] = copies["objects"]

    # Parenting preserves world transforms; unparenting keeps them too.
    parent_value = cube("ParentRoot")
    child = cube("ParentChild", location=(5, 0, 0))
    parented = edit("parent_object", name="ParentChild", new_name="ParentRoot")
    assert parented["parent"] == "ParentRoot"
    assert tuple(round(c, 4) for c in child.matrix_world.translation) == (5, 0, 0)
    edit("transform_object", name="ParentRoot", location=(10, 0, 0))
    bpy.context.view_layer.update()
    assert tuple(round(c, 4) for c in child.matrix_world.translation) == (15, 0, 0)
    unparented = edit("unparent_object", name="ParentChild")
    bpy.context.view_layer.update()
    assert unparented["parent"] is None
    assert tuple(round(c, 4) for c in child.matrix_world.translation) == (15, 0, 0)
    cube("CycleA")
    cube("CycleB", location=(2, 0, 0))
    edit("parent_object", name="CycleB", new_name="CycleA")
    refused("parent_object", "cycle", name="CycleA", new_name="CycleB")
    refused("parent_object", "own parent", name="ParentRoot", new_name="ParentRoot")
    results["parenting"] = list(child.matrix_world.translation)

    # Collection moves create and link a collection without moving geometry.
    location = tuple(child.location)
    moved = edit("move_to_collection", name="ParentChild", new_name="Props", create=True)
    assert moved["collection"] == "Props"
    assert "Props" in bpy.data.collections and "ParentChild" in bpy.data.collections["Props"].objects
    assert tuple(child.location) == location
    refused("move_to_collection", "does not exist", name="ParentChild", new_name="Missing",
            create=False)
    scene = bridge.dispatch("scene_info", {"limit": 1000})
    collection = next(item for item in scene["collections"] if item["name"] == "Props")
    assert collection["objects"] == 1, collection
    detail = bridge.dispatch("object_info", {"name": "ParentChild"})
    assert detail["parent"] is None and detail["collections"] == ["Props"], detail
    results["collections"] = scene["collections"]

    # Join refuses modified sources before creating copies.
    rollback_target = cube("JoinRollback")
    rollback_source = cube("JoinRollbackSource", location=(3, 0, 0))
    edit("add_modifier", name="JoinRollbackSource", kind="bevel", amount=.01)
    rollback_before = tris(rollback_target)
    refused("join_meshes", "without modifiers", name="JoinRollback",
            names=["JoinRollbackSource"])
    assert tris(rollback_target) == rollback_before
    assert "JoinRollbackSource" in bpy.data.objects
    refused("join_meshes", "must not include", name="JoinRollback",
            names=["JoinRollback"])
    results["join_rollback"] = rollback_before

    # Ownership is still required.
    try:
        bridge.dispatch("boolean_mesh", {"name": "JoinRollback", "operand": "JoinRollbackSource",
                                         "operation": "union"})
        raise AssertionError("Unowned boolean succeeded")
    except RuntimeError as exc:
        assert "lease_id" in str(exc)
finally:
    folder.cleanup()

print(json.dumps(results, default=str))
