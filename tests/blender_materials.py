"""Native texture binding and lit-preview restoration in a disposable factory scene."""

import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

with tempfile.TemporaryDirectory() as folder:
    bridge._workspace = Path(folder)
    fixture = bpy.data.images.new("Fixture", width=4, height=4)
    fixture.pixels = [1, 0, 0, 1, 0, 0, 1, 1] * 8
    fixture.filepath_raw = str(Path(folder) / "color.png")
    fixture.file_format = "PNG"
    fixture.save()
    bpy.data.images.remove(fixture)
    state = bridge.dispatch("session_control", {"action": "inspect"})
    lease = bridge.dispatch("session_control", {"action": "claim", "owner": "material-fixture",
                                              "expected_project": state["project_id"]})["lease_id"]
    original_material = bpy.data.objects["Cube"].material_slots[0].material
    bridge.dispatch("assign_material", {"names": ["Cube"], "material_name": "Textured",
                    "base_color_texture": "color.png", "roughness": .7, "metallic": .25,
                    "lease_id": lease})
    material = bpy.data.objects["Cube"].material_slots[0].material
    assert material is not original_material
    shader = material.node_tree.nodes.get("Principled BSDF")
    assert abs(shader.inputs["Roughness"].default_value - .7) < 1e-5
    assert abs(shader.inputs["Metallic"].default_value - .25) < 1e-5
    image = next(n.image for n in material.node_tree.nodes if n.type == "TEX_IMAGE")
    assert image.colorspace_settings.name == "sRGB" and image.packed_file
    before = (bpy.context.scene.camera, bpy.context.scene.world, bpy.context.scene.render.engine,
              set(bpy.data.objects), set(bpy.data.materials), set(bpy.data.lights), set(bpy.data.worlds))
    engines = []

    def rendered(scene):
        engines.append(scene.render.engine)
        assert bpy.data.objects["Light"].hide_render, "Existing light affected studio preview"

    bpy.app.handlers.render_pre.append(rendered)
    try:
        bridge.dispatch("render_preview", {"path": "lit.png", "resolution": 128,
                        "names": ["Cube"], "renderer": "eevee", "lease_id": lease})
    finally:
        bpy.app.handlers.render_pre.remove(rendered)
    assert engines == ["BLENDER_EEVEE"], engines
    after = (bpy.context.scene.camera, bpy.context.scene.world, bpy.context.scene.render.engine,
             set(bpy.data.objects), set(bpy.data.materials), set(bpy.data.lights), set(bpy.data.worlds))
    assert before == after, "Preview leaked state or datablocks"
    assert not bpy.data.objects["Light"].hide_render
    assert Path(folder, "lit.png").stat().st_size > 0
    print(json.dumps({"texture_binding": True, "lit_preview": True, "state_restored": True}))
