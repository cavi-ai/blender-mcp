"""Native integration test: Blender --background --factory-startup --python this_file -- WORKSPACE."""

import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

fixture_state = bridge.dispatch("session_control", {"action": "inspect"})
fixture_lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "native-fixture",
    "expected_project": fixture_state["project_id"],
})["lease_id"]


def owned_dispatch(operation, params):
    return bridge.dispatch(operation, {**params, "lease_id": fixture_lease}
                           if operation not in {"scene_info", "object_info", "runtime_status"}
                           else params)


workspace = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
workspace.mkdir(parents=True, exist_ok=True)
bridge._workspace = workspace
original = owned_dispatch("scene_info", {})
assert "Cube" in {v["name"] for v in original["objects"]}
owned_dispatch("create_primitive", {"name": "SmokeProp", "kind": "cube", "location": [0, 0, 2]})
try:
    owned_dispatch("create_primitive", {"name": "SmokeProp", "kind": "cube"})
except ValueError:
    pass
else:
    raise AssertionError("duplicate name was accepted")
owned_dispatch("transform_object", {"name": "SmokeProp", "scale": [1, 2, 0.5]})
owned_dispatch("set_color", {"name": "SmokeProp", "rgba": [0.2, 0.6, 0.8, 1]})
owned_dispatch("add_modifier", {"name": "SmokeProp", "kind": "bevel", "amount": 0.05})
owned_dispatch("add_modifier", {"name": "SmokeProp", "kind": "decimate", "amount": 0.8})
owned_dispatch("shade_mesh", {"name": "SmokeProp", "smooth": False})
owned_dispatch("unwrap_mesh", {"name": "SmokeProp"})
assert owned_dispatch("object_info", {"name": "SmokeProp"})["uv_layers"] > 0
for extension in ("fbx", "glb"):
    result = owned_dispatch("export_mesh", {"names": ["SmokeProp"], "path": f"prop.{extension}"})
    assert result["bytes"] > 0
    try:
        owned_dispatch("export_mesh", {"names": ["SmokeProp"], "path": f"prop.{extension}"})
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing export was overwritten")
assert owned_dispatch("save_project", {"path": "scene.blend"})["bytes"] > 0
camera_count = len(bpy.data.cameras)
result = owned_dispatch("render_preview", {"path": "preview.png", "resolution": 256})
assert Path(result["path"]).stat().st_size > 0
assert len(bpy.data.cameras) == camera_count
assert bpy.context.scene.camera.name == "Camera"
linked = bpy.data.objects.new("LinkedProp", bpy.data.objects["SmokeProp"].data)
bpy.context.scene.collection.objects.link(linked)
try:
    owned_dispatch("shade_mesh", {"name": "SmokeProp", "smooth": True})
except ValueError:
    pass
else:
    raise AssertionError("editing shared mesh data was allowed")
bpy.data.objects.remove(linked, do_unlink=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(workspace / "prop.glb"))
assert len(bpy.data.objects) == 1, "export included objects outside the explicit mesh list"
assert bpy.data.objects[0].name == "SmokeProp"
print(
    json.dumps(
        {
            "native_smoke": "passed",
            "version": bpy.app.version_string,
            "outputs": sorted(p.name for p in workspace.iterdir()),
        }
    )
)
