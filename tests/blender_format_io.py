"""Native OBJ, STL, PLY and Alembic export and import round trips."""

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
    "action": "claim", "owner": "format-io-fixture",
    "expected_project": state["project_id"]})["lease_id"]


def edit(operation, **params):
    return bridge.dispatch(operation, {**params, "lease_id": lease})


def refused(operation, text, **params):
    try:
        edit(operation, **params)
    except (ValueError, RuntimeError, FileExistsError) as exc:
        assert text in str(exc), exc
    else:
        raise AssertionError(f"{operation} accepted {params}")


def corners(value):
    return {tuple(round(c, 4) for c in value.matrix_world @ v.co) for v in value.data.vertices}


try:
    bpy.ops.mesh.primitive_cube_add(location=(2, 3, 4))
    source = bpy.context.object
    source.name = "IoSource"
    source.data.materials.append(bpy.data.materials.new("IoMaterial"))
    expected = corners(source)
    triangles = {}
    for suffix in ("obj", "stl", "ply", "abc"):
        path = "source." + suffix
        written = edit("export_mesh", names=["IoSource"], path=path)
        assert written["bytes"] == (root / path).stat().st_size > 0, written
        imported = edit("import_" + suffix, path=path, name="Io" + suffix.upper())
        assert imported["format"] == suffix, imported
        meshes = [bpy.data.objects[item["name"]] for item in imported["objects"]
                  if item["type"] == "MESH"]
        assert len(meshes) == 1 and corners(meshes[0]) == expected, (suffix, corners(meshes[0]))
        triangles[suffix] = imported["imported_triangles"]
    assert triangles == dict.fromkeys(triangles, 12), triangles
    assert (root / "source.mtl").is_file()
    assert len(bpy.data.objects["IoOBJ"].material_slots) == 1
    alembic = bpy.data.objects["IoABC"]
    assert not bpy.data.cache_files and not any(
        m.type == "MESH_SEQUENCE_CACHE" for m in alembic.modifiers), list(alembic.modifiers)
    refused("export_mesh", "Refusing to overwrite", names=["IoSource"], path="source.stl")
    (root / "taken.mtl").write_text("")
    refused("export_mesh", "Refusing to overwrite", names=["IoSource"], path="taken.obj")
    assert not (root / "taken.obj").exists()
    refused("export_mesh", "include_empties", names=["IoSource"], path="loose.ply",
            include_empties=True)
    (root / "bad.stl").write_bytes(b"not a mesh")
    (root / "bad.ply").write_bytes(b"ply\nformat ascii 1.0\nelement vertex 0\nend_header\n")
    (root / "bad.abc").write_bytes(b"HDF5 alembic")
    for suffix, text in (("stl", "STL"), ("ply", "PLY"), ("abc", "Alembic")):
        refused("import_" + suffix, text, path="bad." + suffix, name="Bad" + suffix)
    print(json.dumps({"round_trips": sorted(triangles), "triangles": triangles}))
finally:
    folder.cleanup()
