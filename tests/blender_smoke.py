"""Native integration test: Blender --background --factory-startup --python this_file -- WORKSPACE."""

import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

workspace = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
workspace.mkdir(parents=True, exist_ok=True)
bridge._workspace = workspace
original = bridge.dispatch("scene_info", {})
assert "Cube" in {v["name"] for v in original["objects"]}
bridge.dispatch("create_primitive", {"name": "SmokeProp", "kind": "cube", "location": [0, 0, 2]})
try:
    bridge.dispatch("create_primitive", {"name": "SmokeProp", "kind": "cube"})
except ValueError:
    pass
else:
    raise AssertionError("duplicate name was accepted")
bridge.dispatch("transform_object", {"name": "SmokeProp", "scale": [1, 2, 0.5]})
bridge.dispatch("set_color", {"name": "SmokeProp", "rgba": [0.2, 0.6, 0.8, 1]})
bridge.dispatch("add_modifier", {"name": "SmokeProp", "kind": "bevel", "amount": 0.05})
bridge.dispatch("add_modifier", {"name": "SmokeProp", "kind": "decimate", "amount": 0.8})
bridge.dispatch("shade_mesh", {"name": "SmokeProp", "smooth": False})
bridge.dispatch("unwrap_mesh", {"name": "SmokeProp"})
assert bridge.dispatch("object_info", {"name": "SmokeProp"})["uv_layers"] > 0
for extension in ("fbx", "glb"):
    result = bridge.dispatch("export_mesh", {"names": ["SmokeProp"], "path": f"prop.{extension}"})
    assert result["bytes"] > 0
    try:
        bridge.dispatch("export_mesh", {"names": ["SmokeProp"], "path": f"prop.{extension}"})
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing export was overwritten")
assert bridge.dispatch("save_project", {"path": "scene.blend"})["bytes"] > 0
camera_count = len(bpy.data.cameras)
result = bridge.dispatch("render_preview", {"path": "preview.png", "resolution": 256})
assert Path(result["path"]).stat().st_size > 0
assert len(bpy.data.cameras) == camera_count
assert bpy.context.scene.camera.name == "Camera"
linked = bpy.data.objects.new("LinkedProp", bpy.data.objects["SmokeProp"].data)
bpy.context.scene.collection.objects.link(linked)
try:
    bridge.dispatch("shade_mesh", {"name": "SmokeProp", "smooth": True})
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
