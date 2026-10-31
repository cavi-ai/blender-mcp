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

    def test_animations_cameras_and_lights_are_refused(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for key, message in [("animations", "animated"), ("cameras", "Cameras")]:
                document = triangle()
                document[key] = [{}]
                write_glb(root / "prop.glb", document)
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, message):
                    inspect_glb(root, "prop.glb")
            document = triangle()
            document["extensionsUsed"] = ["KHR_lights_punctual"]
            write_glb(root / "prop.glb", document)
            with self.assertRaisesRegex(ValueError, "Light"):
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
