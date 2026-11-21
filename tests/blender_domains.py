"""Run with Blender --background --factory-startup --python-exit-code 1 --python tests/blender_domains.py."""

import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

workspace = Path(tempfile.mkdtemp(prefix="cavi-domains-"))
bridge._workspace = workspace
state = bridge.dispatch("session_control", {"action": "inspect"})
lease = bridge.dispatch("session_control", {
    "action": "claim", "owner": "domain-fixture", "expected_project": state["project_id"],
})["lease_id"]


def call(operation, **params):
    return bridge.dispatch(operation, {"lease_id": lease, **params})


def heights(name):
    deps = bpy.context.evaluated_depsgraph_get()
    evaluated = bpy.data.objects[name].evaluated_get(deps)
    return [vertex.co.z for vertex in evaluated.data.vertices]


cube = bpy.data.objects["Cube"]
original = [vertex.co.copy() for vertex in cube.data.vertices]
try:
    call("sculpt_stroke", name="Cube", amount=1, vertices=[[0, 0, 1], [0, 0, 1], [0, 0, 1]])
except ValueError as exc:
    if "background" not in str(exc):
        raise
else:
    raise AssertionError("headless sculpt stroke reported a deformation")
if any((vertex.co - prior).length > 1e-8 for vertex, prior in zip(cube.data.vertices, original, strict=True)):
    raise AssertionError("refused sculpt stroke changed the mesh")
if bpy.context.mode != "OBJECT":
    raise AssertionError("sculpt stroke left the mode")

created = call("create_geometry_group", name="Cube", new_name="Warp")
if created["domain"]["nodes"] != ["Group Input", "Group Output"] or min(heights("Cube")) >= 0:
    raise AssertionError(created)
call("add_geometry_node", name="Cube", modifier="Warp", new_name="Offset",
     node_type="GeometryNodeSetPosition")
call("link_geometry_node", name="Cube", modifier="Warp", from_node="Group Input",
     from_socket="Geometry", to_node="Offset", to_socket="Geometry")
linked = call("link_geometry_node", name="Cube", modifier="Warp", from_node="Offset",
              from_socket="Geometry", to_node="Group Output", to_socket="Geometry")
if "Offset" not in linked["domain"]["nodes"] or linked["domain"]["links"] < 2:
    raise AssertionError(linked)
bpy.data.node_groups["Warp"].nodes["Offset"].inputs["Offset"].default_value = (0, 0, 1)
shifted = heights("Cube")
if min(shifted) < -0.01 or max(shifted) < 1.5:
    raise AssertionError(shifted)

call("create_primitive", name="Drop", kind="cube", location=[0, 0, 2])
body = call("rigid_body", name="Drop", collision_shape="BOX", body="ACTIVE", mass=1, frames=5)
if body["domain"]["evaluated_location"][2] >= 2:
    raise AssertionError(body["domain"])
if bpy.context.scene.frame_current != 1:
    raise AssertionError("physics bake left the scene frame")
passive = call("rigid_body", name="Cube", collision_shape="CONVEX_HULL", body="PASSIVE", frames=0)
if passive["domain"]["collision_shape"] != "CONVEX_HULL":
    raise AssertionError(passive["domain"])

particles = call("particle_system", name="Cube", count=12, seed=3, new_name="Emitter")
if particles["domain"]["count"] != 12 or particles["domain"]["seed"] != 3:
    raise AssertionError(particles["domain"])
hair = call("hair_curves", name="Cube", new_name="CubeHair", curves=[
    [[0, 0, 0], [0, 0, 1]], [[0.2, 0, 0], [0.2, 0, 1], [0.2, 0.1, 1.2]]])
if (hair["domain"]["curves"], hair["domain"]["points"], hair["parent"]) != (2, 5, "Cube"):
    raise AssertionError(hair)

blur = call("scene_authoring", action="compositor", definition={
    "step": "add_node", "node": "Blur", "node_type": "CompositorNodeBlur"})
call("scene_authoring", action="compositor", definition={
    "step": "add_node", "node": "Soft", "node_type": "CompositorNodeBlur"})
linked_blur = call("scene_authoring", action="compositor", definition={
    "step": "link", "from_node": "Blur", "from_socket": "Image",
    "to_node": "Soft", "to_socket": "Image"})
if blur["type"] != "COMPOSITOR" or linked_blur["link_count"] < 1:
    raise AssertionError((blur, linked_blur))

data = bpy.data.volumes.new("Fog")
fog = bpy.data.objects.new("Fog", data)
bpy.context.scene.collection.objects.link(fog)
volume = call("volume_to_mesh", name="Cube", source="Fog", resolution=16)
if volume["domain"] != {"kind": "volume_to_mesh", "source": "Fog", "resolution": 16}:
    raise AssertionError(volume["domain"])
if cube.modifiers["VolumeMesh"].object != fog or cube.modifiers["VolumeMesh"].voxel_amount != 16:
    raise AssertionError("volume modifier did not keep its source")

(workspace / "notes.vdb").write_bytes(b"not a volume")
try:
    call("import_vdb", path="notes.vdb", name="Notes")
except ValueError as exc:
    if "OpenVDB" not in str(exc):
        raise
else:
    raise AssertionError("non-vdb bytes were imported")
(workspace / "magic.vdb").write_bytes((0x56444220).to_bytes(8, "little") + bytes(64))
before = {item.name for item in bpy.data.objects}
try:
    call("import_vdb", path="magic.vdb", name="Magic")
except (ValueError, RuntimeError):
    pass
else:
    raise AssertionError("incomplete volume bytes were imported")
if {item.name for item in bpy.data.objects} != before:
    raise AssertionError("failed volume import left an object")
