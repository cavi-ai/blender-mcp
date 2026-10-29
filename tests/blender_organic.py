"""Native custom geometry, surface modifier and preview isolation checks."""

import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

bridge._workspace = Path(sys.argv[sys.argv.index("--") + 1]).resolve()
bridge._workspace.mkdir(parents=True, exist_ok=True)
vertices = [
    [-1, -1, -1],
    [1, -1, -1],
    [1, 1, -1],
    [-1, 1, -1],
    [-1, -1, 1],
    [1, -1, 1],
    [1, 1, 1],
    [-1, 1, 1],
]
faces = [[3, 2, 1, 0], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
before = len(bpy.data.meshes)
try:
    bridge.dispatch("create_mesh", {"name": "Bad", "vertices": vertices, "faces": [[0, 1, 9]]})
except ValueError:
    pass
else:
    raise AssertionError("Invalid mesh was accepted")
assert len(bpy.data.meshes) == before
for name, kind, amount in (("Smooth", "subdivision", 2), ("Fused", "voxel_remesh", 0.1)):
    bridge.dispatch("create_mesh", {"name": name, "vertices": vertices, "faces": faces})
    bridge.dispatch("shade_mesh", {"name": name, "smooth": True})
    bridge.dispatch("add_modifier", {"name": name, "kind": kind, "amount": amount})
    evaluated = bpy.data.objects[name].evaluated_get(bpy.context.evaluated_depsgraph_get())
    assert len(evaluated.data.polygons) > 6
    assert all(p.use_smooth for p in evaluated.data.polygons)
    try:
        bridge.dispatch("add_modifier", {"name": name, "kind": kind, "amount": amount})
    except ValueError:
        pass
    else:
        raise AssertionError("Unbounded modifier stacking was accepted")
bridge.dispatch("create_mesh", {"name": "Budget", "vertices": vertices, "faces": faces})
for kind, amount in (("subdivision", 1.5), ("subdivision", 4), ("voxel_remesh", 0.005)):
    try:
        bridge.dispatch("add_modifier", {"name": "Budget", "kind": kind, "amount": amount})
    except ValueError:
        pass
    else:
        raise AssertionError("Unsafe surface operation was accepted")
assert not bpy.data.objects["Budget"].modifiers
bridge.dispatch(
    "add_modifier", {"name": "Budget", "kind": "subdivision", "amount": 1, "apply": True}
)
assert not bpy.data.objects["Budget"].modifiers, "Baking left the modifier unevaluated"
assert len(bpy.data.objects["Budget"].data.polygons) == 24
visibility = {o.name: o.hide_render for o in bpy.context.scene.objects}
for extra in ({"names": ["Missing"]}, {"direction": [0, 0, 0]}, {"color_mode": "invalid"}):
    try:
        bridge.dispatch("render_preview", {"path": "invalid.png", "resolution": 64, **extra})
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid preview selection or direction was accepted")
assert not (bridge._workspace / "invalid.png").exists()
bridge.dispatch(
    "render_preview",
    {"path": "custom.png", "resolution": 256, "names": ["Smooth"], "direction": [0, -2, 1]},
)
assert {o.name: o.hide_render for o in bpy.context.scene.objects} == visibility
bridge.dispatch("set_color", {"name": "Smooth", "rgba": [0, 0, 1, 1]})
color = bpy.data.objects["Smooth"].data.color_attributes.new(
    name="Color", type="FLOAT_COLOR", domain="CORNER"
)
for entry in color.data:
    entry.color = (1, 0, 0, 1)
previous_color_mode = bpy.context.scene.display.shading.color_type
bridge.dispatch(
    "render_preview",
    {"path": "vertex.png", "resolution": 64, "names": ["Smooth"], "color_mode": "vertex"},
)
pixels = bpy.data.images.load(str(bridge._workspace / "vertex.png"))
center = (32 * 64 + 32) * 4
assert pixels.pixels[center] > pixels.pixels[center + 2] * 2
assert bpy.context.scene.display.shading.color_type == previous_color_mode
bridge.dispatch("export_mesh", {"names": ["Smooth"], "path": "custom.glb"})
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(bridge._workspace / "custom.glb"))
assert len(bpy.context.scene.objects) == 1
assert len(bpy.data.objects["Smooth"].data.polygons) > 6
print("Organic mesh native checks passed")
