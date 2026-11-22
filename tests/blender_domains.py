"""Run with Blender --background --factory-startup --python-exit-code 1 --python tests/blender_domains.py."""

import sys
import tempfile
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from cavi_blender_mcp import blender_bridge as bridge

folder = tempfile.TemporaryDirectory(prefix="cavi-domains-")
workspace = Path(folder.name)
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
call("add_geometry_node", name="Cube", modifier="Warp", new_name="Position",
     node_type="GeometryNodeInputPosition")
try:
    call("link_geometry_node", name="Cube", modifier="Warp", from_node="Position",
         from_socket="Position", to_node="Group Output", to_socket="Geometry")
except ValueError:
    pass
else:
    raise AssertionError("invalid geometry socket link was accepted")
assert len(bpy.data.node_groups["Warp"].links) == 1 and min(heights("Cube")) < 0
call("add_geometry_node", name="Cube", modifier="Warp", new_name="Offset",
     node_type="GeometryNodeSetPosition")
call("link_geometry_node", name="Cube", modifier="Warp", from_node="Group Input",
     from_socket="Geometry", to_node="Offset", to_socket="Geometry")
linked = call("link_geometry_node", name="Cube", modifier="Warp", from_node="Offset",
              from_socket="Geometry", to_node="Group Output", to_socket="Geometry")
if "Offset" not in linked["domain"]["nodes"] or linked["domain"]["links"] < 2:
    raise AssertionError(linked)
before_count = len(bpy.data.node_groups["Warp"].links)
call("link_geometry_node", name="Cube", modifier="Warp", from_node="Offset",
     from_socket="Geometry", to_node="Group Output", to_socket="Geometry")
assert len(bpy.data.node_groups["Warp"].links) == before_count
bpy.data.node_groups["Warp"].nodes["Offset"].inputs["Offset"].default_value = (0, 0, 1)
shifted = heights("Cube")
if min(shifted) < -0.01 or max(shifted) < 1.5:
    raise AssertionError(shifted)

call("create_primitive", name="Drop", kind="cube", location=[0, 0, 2])
scene = bpy.context.scene
scene.frame_set(3, subframe=.375)
body = call("rigid_body", name="Drop", collision_shape="BOX", body="ACTIVE", mass=1, frames=5)
if body["domain"]["evaluated_location"][2] >= 2:
    raise AssertionError(body["domain"])
if (scene.frame_current, scene.frame_subframe) != (3, .375):
    raise AssertionError("physics bake changed the scene frame")
prior_settings = (bpy.data.objects["Drop"].rigid_body.mass, scene.frame_current, scene.frame_subframe)
try:
    call("rigid_body", name="Drop", collision_shape="BOX", body="ACTIVE", mass=2, frames=5)
except ValueError:
    pass
else:
    raise AssertionError("repeated rigid cache bake was accepted")
assert (bpy.data.objects["Drop"].rigid_body.mass, scene.frame_current, scene.frame_subframe) == prior_settings
cloth = bpy.data.objects.new("Cloth", cube.data.copy())
scene.collection.objects.link(cloth)
cloth_modifier = cloth.modifiers.new("Cloth", "CLOTH")
call("create_primitive", name="SecondDrop", kind="cube", location=[3, 0, 2])
try:
    call("rigid_body", name="SecondDrop", collision_shape="BOX", body="ACTIVE", frames=5)
except ValueError as error:
    assert "other point caches" in str(error)
else:
    raise AssertionError("bake with unrelated cloth cache was accepted")
assert bpy.data.objects["SecondDrop"].rigid_body is None and not cloth_modifier.point_cache.is_baked
bpy.data.objects.remove(cloth, do_unlink=True)
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

before_groups = set(bpy.data.node_groups)
assert bpy.context.scene.compositing_node_group is None
try:
    call("scene_authoring", action="compositor", definition={
        "step": "add_node", "node": "Invalid", "node_type": "NoSuchNode"})
except ValueError:
    pass
else:
    raise AssertionError("invalid compositor node was accepted")
assert bpy.context.scene.compositing_node_group is None and set(bpy.data.node_groups) == before_groups

blur = call("scene_authoring", action="compositor", definition={
    "step": "add_node", "node": "Blur", "node_type": "CompositorNodeBlur"})
call("scene_authoring", action="compositor", definition={
    "step": "add_node", "node": "Soft", "node_type": "CompositorNodeBlur"})
linked_blur = call("scene_authoring", action="compositor", definition={
    "step": "link", "from_node": "Blur", "from_socket": "Image",
    "to_node": "Soft", "to_socket": "Image"})
before_links = [(link.from_node.name, link.to_node.name) for link in scene.compositing_node_group.links]
try:
    call("scene_authoring", action="compositor", definition={
        "step": "link", "from_node": "Soft", "from_socket": "Image",
        "to_node": "Blur", "to_socket": "Image"})
except ValueError as error:
    assert "cycle" in str(error)
else:
    raise AssertionError("cyclic compositor link was accepted")
assert [(link.from_node.name, link.to_node.name) for link in scene.compositing_node_group.links] == before_links
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

source_data = bpy.data.volumes.new("SourceVolume")
source = bpy.data.objects.new("SourceVolume", source_data)
scene.collection.objects.link(source)
modifier = source.modifiers.new("Density", "MESH_TO_VOLUME")
modifier.object = bpy.data.objects["Drop"]
modifier.resolution_mode = 'VOXEL_AMOUNT'
modifier.voxel_amount = 16
bpy.context.view_layer.update()
vdb_path = workspace / "density.vdb"
evaluated = source.evaluated_get(bpy.context.evaluated_depsgraph_get())
assert evaluated.data.grids.save(str(vdb_path))
imported = call("import_vdb", path="density.vdb", name="Density")
volume_data = bpy.data.objects["Density"].data
assert imported['domain']['grids'] == ['density'] and Path(volume_data.filepath).resolve() == vdb_path.resolve(), (imported, volume_data.filepath, vdb_path)
assert not list(workspace.glob('.cavi-import-*.vdb'))
volume_data.grids.unload()
volume_data.grids.load()
assert [grid.name for grid in volume_data.grids] == ['density']

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

folder.cleanup()
