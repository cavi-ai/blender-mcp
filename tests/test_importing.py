import json
import struct
import tempfile
import unittest
from pathlib import Path


def write_glb(path, document, binary=b"\x00" * 44):
    payload = json.dumps(document).encode()
    payload += b" " * (-len(payload) % 4)
    binary += b"\x00" * (-len(binary) % 4)
    chunks = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 12 + len(chunks)) + chunks)


def triangle():
    return {
        "asset": {"version": "2.0"}, "buffers": [{"byteLength": 44}],
        "accessors": [{"componentType": 5126, "count": 3, "type": "VEC3"},
                      {"componentType": 5123, "count": 3, "type": "SCALAR"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0,
    }


def skinned():
    document = triangle()
    document["buffers"][0]["byteLength"] = 1024
    document["accessors"] += [
        {"componentType": 5121, "count": 3, "type": "VEC4"},
        {"componentType": 5126, "count": 3, "type": "VEC4"},
        {"componentType": 5126, "count": 1, "type": "MAT4"},
    ]
    document["meshes"][0]["primitives"][0]["attributes"].update(
        {"JOINTS_0": 2, "WEIGHTS_0": 3})
    document["nodes"] = [{"mesh": 0, "skin": 0}, {"name": "Joint"}]
    document["scenes"] = [{"nodes": [0, 1]}]
    document["skins"] = [{"joints": [1], "inverseBindMatrices": 4}]
    return document


def animated():
    document = triangle()
    document["buffers"][0]["byteLength"] = 4096
    document["accessors"] += [
        {"componentType": 5126, "count": 2, "type": "SCALAR"},
        {"componentType": 5126, "count": 2, "type": "VEC3"},
    ]
    document["animations"] = [{
        "channels": [{"sampler": 0, "target": {"node": 0, "path": "translation"}}],
        "samplers": [{"input": 2, "output": 3, "interpolation": "LINEAR"}],
    }]
    return document


class ObjPreflightTests(unittest.TestCase):
    def test_obj_geometry_and_material_libraries_are_bounded(self):
        from cavi_blender_mcp.importing import inspect_obj

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "mat.mtl").write_text("newmtl Mat\n")
            (root / "prop.obj").write_text(
                "mtllib mat.mtl\no Prop\nv 0 0 0\nv 1 0 0\nv 0 1 0\n"
                "f 1 2 3\n")
            report = inspect_obj(root, "prop.obj")
            self.assertEqual((report["format"], report["vertices"], report["faces"],
                              report["objects"]), ("obj", 3, 1, 1))
            self.assertEqual(report["mtllibs"], ["mat.mtl"])

    def test_obj_rejects_external_or_missing_textures(self):
        from cavi_blender_mcp.importing import inspect_obj

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "prop.obj").write_text("mtllib mat.mtl\nv 0 0 0\nf 1 1 1\n")
            for texture in ("../outside.png", "missing.png"):
                (root / "mat.mtl").write_text(f"newmtl Mat\nmap_Kd {texture}\n")
                with self.subTest(texture=texture), self.assertRaisesRegex(
                        ValueError, "workspace"):
                    inspect_obj(root, "prop.obj")

    def test_obj_rejects_missing_or_external_materials_and_empty_geometry(self):
        from cavi_blender_mcp.importing import inspect_obj

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "missing.obj").write_text("mtllib missing.mtl\nv 0 0 0\nf 1 1 1\n")
            with self.assertRaisesRegex(ValueError, "material libraries"):
                inspect_obj(root, "missing.obj")
            (root / "empty.obj").write_text("# no geometry\n")
            with self.assertRaisesRegex(ValueError, "geometry"):
                inspect_obj(root, "empty.obj")
            with tempfile.TemporaryDirectory() as outside:
                target = Path(outside) / "outside.obj"
                target.write_text("v 0 0 0\nf 1 1 1\n")
                (root / "escape.obj").symlink_to(target)
                with self.assertRaisesRegex(ValueError, "workspace"):
                    inspect_obj(root, "escape.obj")
                with self.assertRaisesRegex(ValueError, "workspace"):
                    inspect_obj(root, str(target))


class FbxPreflightTests(unittest.TestCase):
    def test_binary_and_ascii_fbx_headers_are_hashed(self):
        from cavi_blender_mcp.importing import inspect_fbx

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, content, binary in (
                ("binary.fbx", b"Kaydara FBX Binary  \x00\x1a\x00" + b"\x00" * 64, True),
                ("ascii.fbx", b"; FBX 7.4.0 project file\n" + b"\x00" * 64, False),
            ):
                (root / name).write_bytes(content)
                report = inspect_fbx(root, name)
                self.assertEqual(report["format"], "fbx")
                self.assertEqual(report["binary"], binary)
                self.assertEqual(len(report["sha256"]), 64)

    def test_bad_extension_header_and_workspace_are_refused(self):
        from cavi_blender_mcp.importing import inspect_fbx

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "model.obj").write_bytes(b"Kaydara FBX Binary")
            (root / "bad.fbx").write_bytes(b"not an fbx file")
            with self.assertRaisesRegex(ValueError, "FBX"):
                inspect_fbx(root, "model.obj")
            with self.assertRaisesRegex(ValueError, "FBX"):
                inspect_fbx(root, "bad.fbx")
            with tempfile.TemporaryDirectory() as outside:
                target = Path(outside) / "outside.fbx"
                target.write_bytes(b"Kaydara FBX Binary  \x00")
                (root / "escape.fbx").symlink_to(target)
                for name in ("../outside.fbx", "escape.fbx", str(target)):
                    with self.subTest(name=name), self.assertRaisesRegex(ValueError, "workspace"):
                        inspect_fbx(root, name)


class ImportPreflightTests(unittest.TestCase):
    def test_node_cycles_are_refused_before_blender_traverses_them(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = triangle()
            document["nodes"][0]["children"] = [0]
            write_glb(root / "prop.glb", document)
            with self.assertRaisesRegex(ValueError, "hierarchy"):
                inspect_glb(root, "prop.glb")

    def test_hidden_geometry_compression_is_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = triangle()
            document["meshes"][0]["primitives"][0]["extensions"] = {
                "KHR_draco_mesh_compression": {"bufferView": 0}
            }
            write_glb(root / "prop.glb", document)
            with self.assertRaisesRegex(ValueError, "Compressed"):
                inspect_glb(root, "prop.glb")

    def test_static_embedded_mesh_is_bounded_and_hashed(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_glb(root / "prop.glb", triangle())
            report = inspect_glb(root, "prop.glb")
            self.assertEqual(report["vertices"], 3)
            self.assertEqual(report["triangles"], 1)
            self.assertEqual(len(report["sha256"]), 64)

    def test_outside_or_symlinked_sources_are_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "workspace"
            root.mkdir()
            write_glb(root.parent / "outside.glb", triangle())
            (root / "linked.glb").symlink_to(root.parent / "outside.glb")
            for name in ["../outside.glb", "linked.glb", str(root.parent / "outside.glb")]:
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, "workspace"):
                    inspect_glb(root, name)

    def test_external_dependencies_are_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for uri in ["../private.png", "https://example.com/private.png", "file:///private.png"]:
                document = triangle()
                document["images"] = [{"uri": uri}]
                write_glb(root / "prop.glb", document)
                with self.subTest(uri=uri), self.assertRaisesRegex(ValueError, "external"):
                    inspect_glb(root, "prop.glb")

    def test_skinned_glb_is_bounded_and_reported(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_glb(root / "prop.glb", skinned(), b"\x00" * 1024)
            report = inspect_glb(root, "prop.glb")
            self.assertEqual((report["skins"], report["joints"], report["skinned_meshes"]),
                             (1, 1, 1))

    def test_animated_glb_is_bounded_and_reported(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_glb(root / "prop.glb", animated(), b"\x00" * 4096)
            report = inspect_glb(root, "prop.glb")
            self.assertEqual((report["animations"], report["animation_channels"],
                              report["animation_keys"]), (1, 1, 2))
            document = animated()
            document["animations"][0]["samplers"][0]["interpolation"] = "CUBICSPLINE"
            document["accessors"][3]["count"] = 6
            write_glb(root / "prop.glb", document, b"\x00" * 4096)
            report = inspect_glb(root, "prop.glb")
            self.assertEqual(report["animation_keys"], 2)

    def test_cameras_and_lights_are_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = triangle()
            document["cameras"] = [{}]
            write_glb(root / "prop.glb", document)
            with self.assertRaisesRegex(ValueError, "Cameras"):
                inspect_glb(root, "prop.glb")
            document = triangle()
            document["extensionsUsed"] = ["KHR_lights_punctual"]
            write_glb(root / "prop.glb", document)
            with self.assertRaisesRegex(ValueError, "Light"):
                inspect_glb(root, "prop.glb")

    def test_malformed_animations_are_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cases = []

            document = animated()
            document["animations"][0]["channels"] = []
            cases.append((document, "at least one channel"))

            document = animated()
            document["animations"][0]["samplers"] = []
            cases.append((document, "at least one sampler"))

            document = animated()
            document["animations"][0]["channels"][0]["sampler"] = 9
            cases.append((document, "sampler reference"))

            document = animated()
            document["animations"][0]["channels"][0]["target"]["node"] = 9
            cases.append((document, "invalid node"))

            document = animated()
            document["animations"][0]["channels"][0]["target"]["path"] = "weights"
            cases.append((document, "translation, rotation or scale"))

            document = animated()
            document["accessors"][2]["type"] = "VEC3"
            cases.append((document, "FLOAT SCALAR"))

            document = animated()
            document["accessors"][3]["componentType"] = 5123
            cases.append((document, "FLOAT accessors"))

            document = animated()
            document["accessors"][2]["count"] = 100001
            document["accessors"][3]["count"] = 100001
            cases.append((document, "100000 keys"))

            document = animated()
            document["animations"][0]["samplers"][0]["interpolation"] = "BEZIER"
            cases.append((document, "interpolation"))

            document = animated()
            document["accessors"][3]["count"] = 3
            cases.append((document, "output count"))

            document = animated()
            document["animations"][0]["channels"][0]["target"]["path"] = "rotation"
            cases.append((document, "output type"))

            document = animated()
            document["animations"][0]["channels"].append(
                {"sampler": 0, "target": {"node": 0, "path": "scale"}})
            cases.append((document, "mix target paths"))

            document = animated()
            document["animations"] = [
                json.loads(json.dumps(document["animations"][0])) for _ in range(33)]
            cases.append((document, "32 animations"))

            document = triangle()
            document["buffers"][0]["byteLength"] = 4096
            document["accessors"] += [
                {"componentType": 5126, "count": 100000, "type": "SCALAR"},
                {"componentType": 5126, "count": 100000, "type": "VEC3"},
            ]
            sample = {"channels": [{"sampler": 0,
                                    "target": {"node": 0, "path": "translation"}}],
                      "samplers": [{"input": 2, "output": 3, "interpolation": "LINEAR"}]}
            document["animations"] = [json.loads(json.dumps(sample)) for _ in range(3)]
            cases.append((document, "256000 animation keys"))

            for index, (document, message) in enumerate(cases):
                with self.subTest(case=index):
                    write_glb(root / "prop.glb", document, b"\x00" * 4096)
                    with self.assertRaisesRegex(ValueError, message):
                        inspect_glb(root, "prop.glb")

    def test_malformed_skin_bindings_are_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            cases = []

            document = skinned()
            del document["meshes"][0]["primitives"][0]["attributes"]["JOINTS_0"]
            cases.append((document, "JOINTS_0"))

            document = skinned()
            document["meshes"][0]["primitives"][0]["attributes"]["JOINTS_1"] = 2
            cases.append((document, "four skin"))

            document = skinned()
            document["skins"][0]["joints"] = [9]
            cases.append((document, "invalid node"))

            document = skinned()
            document["skins"][0]["joints"] = [1, 1]
            cases.append((document, "unique joints"))

            document = skinned()
            document["accessors"][4]["type"] = "VEC3"
            cases.append((document, "MAT4"))

            document = skinned()
            document["accessors"][4]["count"] = 2
            cases.append((document, "match the joints"))

            document = skinned()
            document["accessors"][3]["componentType"] = 5121
            cases.append((document, "normalized"))

            document = skinned()
            document["accessors"][3]["type"] = "VEC3"
            cases.append((document, "VEC4"))

            document = skinned()
            document["accessors"][2]["componentType"] = 5122
            cases.append((document, "unsigned VEC4"))

            document = skinned()
            document["accessors"][2]["count"] = 2
            cases.append((document, "position count"))

            document = skinned()
            document["nodes"][0] = {"skin": 0}
            cases.append((document, "reference a mesh"))

            document = skinned()
            document["nodes"][0]["skin"] = 9
            cases.append((document, "Invalid skin reference"))

            document = skinned()
            document["skins"] = [{"joints": [1]} for _ in range(17)]
            cases.append((document, "16 skins"))

            for index, (document, message) in enumerate(cases):
                with self.subTest(case=index):
                    write_glb(root / "prop.glb", document, b"\x00" * 1024)
                    with self.assertRaisesRegex(ValueError, message):
                        inspect_glb(root, "prop.glb")

    def test_declared_geometry_cannot_exceed_memory_budget(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = triangle()
            document["accessors"][0]["count"] = 500001
            write_glb(root / "prop.glb", document)
            with self.assertRaisesRegex(ValueError, "geometry"):
                inspect_glb(root, "prop.glb")

    def test_truncated_container_is_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_glb(root / "prop.glb", triangle())
            path = root / "prop.glb"
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "GLB"):
                inspect_glb(root, "prop.glb")

    def test_oversized_embedded_image_is_refused_before_decode(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 32768, 32768)
            document = triangle()
            document["buffers"][0]["byteLength"] = len(image)
            document["bufferViews"] = [{"buffer": 0, "byteOffset": 0, "byteLength": len(image)}]
            document["images"] = [{"bufferView": 0, "mimeType": "image/png"}]
            write_glb(root / "prop.glb", document, image)
            with self.assertRaisesRegex(ValueError, "image"):
                inspect_glb(root, "prop.glb")
