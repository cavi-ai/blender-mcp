"""Native skin-weight diagnostics, linked actions and read-only state."""
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

bpy.ops.object.armature_add()
rig = bpy.context.object
rig.name = "FixtureRig"
data = bpy.data.meshes.new("Skin")
data.from_pydata([(0, 0, 0), (1, 0, 0), (0, 0, 1)], [], [(0, 1, 2)])
skin = bpy.data.objects.new("Skin", data)
bpy.context.scene.collection.objects.link(skin)
skin.modifiers.new("Skin", "ARMATURE").object = rig
group = skin.vertex_groups.new(name="Bone")
group.add([0], 1, "REPLACE")
group.add([1], .5, "REPLACE")
skin.vertex_groups.new(name="SelectionMask").add([2], 1, "REPLACE")
rig.animation_data_create()
rig.keyframe_insert("location", frame=1)
rig.location.x = 1
rig.keyframe_insert("location", frame=11)
action = rig.animation_data.action
action.name = "FixtureWalk"
bpy.context.scene.frame_set(5)
before = bridge.dispatch("scene_info", {})
counts = (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.actions))
result = bridge.dispatch("inspect_rig", {"armature": rig.name, "meshes": [skin.name]})
assert result["bones"][0]["name"] == "Bone"
assert result["root_bones"] == ["Bone"]
assert result["clips"][0]["name"] == "FixtureWalk"
assert result["clips"][0]["frame_range"] == [1, 11]
weights = result["meshes"][0]["weights"]
assert weights["unweighted_vertices"] == 1
assert weights["unnormalized_vertices"] == 1
assert weights["ignored_groups"] == ["SelectionMask"]
assert weights["max_influences"] == 1
assert result["meshes"][0]["triangles"] == 1
assert bridge.dispatch("scene_info", {}) == before
assert counts == (len(bpy.data.objects), len(bpy.data.meshes), len(bpy.data.actions))
assert rig.animation_data.action == action
group.add([1, 2], 1, "REPLACE")
good = bridge.dispatch("inspect_rig", {"armature": rig.name, "meshes": [skin.name]})
assert good["meshes"][0]["weights"]["unweighted_vertices"] == 0
assert good["meshes"][0]["weights"]["unnormalized_vertices"] == 0
bpy.context.view_layer.objects.active = rig
bpy.ops.object.mode_set(mode="EDIT")
second = rig.data.edit_bones.new("Second")
second.head, second.tail = (1, 0, 0), (1, 0, 1)
bpy.ops.object.mode_set(mode="OBJECT")
skin.vertex_groups.new(name="Second").add([0], 1, "REPLACE")
over = bridge.dispatch("inspect_rig", {"armature": rig.name, "meshes": [skin.name],
                                      "max_influences": 1})
assert over["meshes"][0]["weights"]["over_limit_vertices"] == 1
assert over["meshes"][0]["weights"]["max_influences"] == 2
for params, message in [
    ({"armature": skin.name, "meshes": [skin.name]}, "armature"),
    ({"armature": rig.name, "meshes": [skin.name, skin.name]}, "unique"),
    ({"armature": rig.name, "meshes": [skin.name], "max_influences": 0}, "max_influences"),
]:
    try:
        bridge.dispatch("inspect_rig", params)
        raise AssertionError("invalid request accepted")
    except ValueError as exc:
        assert message in str(exc)
skin.modifiers.new("Unbounded", "SUBSURF")
try:
    bridge.dispatch("inspect_rig", {"armature": rig.name, "meshes": [skin.name]})
    raise AssertionError("unsupported modifier evaluated")
except ValueError as exc:
    assert "modifier" in str(exc)
print(json.dumps({"skin_diagnostics": True, "linked_actions": True, "read_only": True}))
