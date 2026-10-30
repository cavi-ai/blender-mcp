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

    def test_animation_and_skin_are_refused_before_import(self):
        from cavi_blender_mcp.importing import inspect_glb

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for key in ["animations", "skins", "cameras"]:
                document = triangle()
                document[key] = [{}]
                write_glb(root / "prop.glb", document)
                with self.subTest(key=key), self.assertRaisesRegex(ValueError, "static"):
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
