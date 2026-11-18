"""Native frame-sequence renders: numbered files, hashes and atomic refusal."""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory()
root = Path(folder.name)
bridge._workspace = root
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "render-sequence-fixture",
    "expected_project": state["project_id"]})["lease_id"]
SPEC = {"path": "shot.png", "camera": "Camera", "engine": "cycles", "device": "CPU",
        "width": 32, "height": 16, "samples": 1, "file_format": "png", "bit_depth": "8",
        "transparent": False, "view_transform": "Standard", "exposure": 0, "gamma": 1,
        "denoise": False, "frame": 1, "end_frame": 3, "frame_step": 1, "threads": 2,
        "cycles_time_limit": 10, "max_pixels": 512}


def render(**changes):
    return bridge.dispatch("owned_edit", {"operation": "scene_authoring", "params": {
        "action": "render", "definition": {**SPEC, **changes}, "lease_id": lease}})


def refused(text, **changes):
    try:
        render(**changes)
    except (ValueError, RuntimeError, FileExistsError) as exc:
        assert text in str(exc), exc
    else:
        raise AssertionError(f"render accepted {changes}")


try:
    cube = bpy.data.objects["Cube"]
    for frame, height in ((1, 0), (3, 3)):
        cube.location.z = height
        cube.keyframe_insert("location", frame=frame)
    result = render()
    frames = result["frames"]
    assert [item["frame"] for item in frames] == [1, 2, 3], frames
    assert [Path(item["path"]).name for item in frames] == [
        "shot_0001.png", "shot_0002.png", "shot_0003.png"], frames
    for item in frames:
        assert item["sha256"] == hashlib.sha256(Path(item["path"]).read_bytes()).hexdigest()
    assert len({item["sha256"] for item in frames}) == 3, frames
    assert result["path"] == frames[0]["path"] and bpy.context.scene.frame_current == 3
    stepped = render(path="step.png", end_frame=5, frame_step=2)
    assert [item["frame"] for item in stepped["frames"]] == [1, 3, 5], stepped
    still = render(path="still.png", frame=2, end_frame=None)
    assert "frames" not in still and still["camera_projection"]["available"], still
    assert still["sha256"] == frames[1]["sha256"], still
    (root / "clash_0002.png").write_bytes(b"taken")
    refused("Refusing to overwrite", path="clash.png")
    assert not (root / "clash_0001.png").exists() and not (root / "clash_0003.png").exists()
    refused("cycles_time_limit", path="slow.png", cycles_time_limit=0)
    refused("frame", path="back.png", frame=4)
    print(json.dumps({"frames": [item["frame"] for item in frames],
                      "stepped": [item["frame"] for item in stepped["frames"]]}))
finally:
    folder.cleanup()
