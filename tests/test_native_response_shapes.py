"""Response-shape fixtures derived from native implementation return branches."""
import copy
import unittest

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from cavi_blender_mcp import contracts


def object_info(**extra):
    return {"name": "Prop", "type": "MESH", "location": [0., 0., 0.],
            "rotation_degrees": [0., 0., 0.], "rotation_mode": "XYZ", "scale": [1., 1., 1.],
            "dimensions": [1., 1., 1.], "parent": None, "children": 0,
            "collections": [], "modifiers": [], **extra}


def cases():
    return {
        "RigInspection": [{"file": None, "dirty": False, "blender_version": "5.2.3",
            "frame": 1, "fps": 24., "armature": "Rig", "pose_position": "POSE",
            "root_bones": ["Root"], "deform_bones": 1, "bones": [], "meshes": [],
            "actions": [], "action_count": 0, "clips": [], "active_action": None,
            "nla_enabled": False, "not_checked": ["Unity import"], "project_id": "project"}],
        "ObjectEditResult": [object_info(), object_info(shape_keys=0, shape_key_names=[]),
            {"source": "Prop", "count": 1, "linked": True, "offset": [1., 0., 0.], "objects": ["Copy"]}],
        "RigEditResult": [object_info(bone_count=1, bones=[]),
            {"armature": "Rig", "bone_count": 1, "bindings": 1, "meshes": []},
            object_info(before={}, after={}, options={}),
            object_info(frame=1, reset=True, posed=["Root"]),
            object_info(active_action=None, action_slot=None, nla_enabled=False, nla_tracks=[], nla_strips=0),
            {"action": "Walk", "previous": "Old"}, {"deleted": "Walk", "action_count": 0},
            object_info(action="Walk", mapped=[{"source": "Root", "target": "Root"}],
                        frames=[1., 24.], samples=2, action_slot=None)],
        "MeshEditResult": [object_info(uv_layer="UVMap"),
            object_info(triangles_before=20, triangles_target=10, triangles=10,
                        target=10, achieved=10, preservation="weighted", warnings=[]),
            object_info(faces_target=10, faces=10, quad_ratio=1.),
            object_info(before={"vertices": 8}, after={"vertices": 7}, delta={"vertices": -1},
                        merged_vertices=1, loose_removed=0, flipped_faces=0, steps=["merge"]),
            object_info(texture_resolution=1024, density_before={}, density_after={},
                        uv_bounds={"min": [0., 0.], "max": [1., 1.]}, packed=True),
            {"collection": "LOD", "base": "Prop", "levels": [], "source_renamed": False, "warnings": []},
            {"source": "Prop", "shape": "box", "count": 1, "objects": [], "uniform_scale": True},
            *[{"source": "Prop", "by": by, "count": 2, "triangles_before": 24,
               "parts": [object_info(part=0, material_index=0 if by == "materials" else None),
                         object_info(name="Prop_part_01", part=1,
                                     material_index=1 if by == "materials" else None)]}
              for by in ("materials", "loose_parts")]],
        "MaterialAssignment": [{"material": "Clay", "objects": ["Prop"], "slot": 0,
            "updated": False, "material_users": 1, "base_color_srgb": [1., 1., 1., 1.],
            "roughness": .5, "metallic": 0., "base_color_texture": None,
            "textures": {}, "config": {}, "texture_packed": True}],
        "MapBakeResult": [{"bit_depth": 16, "color_space": "Non-Color",
            "normal_channels": ["+X", "+Y", "+Z"], "path": "normal.png", "bytes": 128, "sha256": "a" * 64,
            "map": "normal", "resolution": 16, "samples": 1, "margin": 2,
            "cage_extrusion": 0., "max_ray_distance": 0., "normal_space": "TANGENT",
            "uv_layer": "UVMap", "low": "Prop", "high": [], "selected_to_active": False, "isolate": True}],
        "LevelEditResult": [{"name": "Terrain", "resolution": 16, "size": [10., 10.],
            "height": 2., "minimum": 0., "maximum": 2., "vertices": 256, "triangles": 450, "source": "noise"},
            {"collection": None, "count": 1, "objects": [{"name": "Tree", "source": "Prop", "linked": True}]},
            {"terrain": "Terrain", "offset": 0., "aligned": False, "objects": []}],
        "ScatterResult": [{"name": "Terrain", "modifier": "Scatter", "node_group": "Scatter",
            "collection": "Trees", "estimated_instances": 10, "instances": None,
            "evaluated_triangles": None, "realize": False, "seed": 1}],
    }


class NativeResponseShapes(unittest.TestCase):
    def test_action_shapes_round_trip_without_wrappers_or_inserted_nulls(self):
        for name, records in cases().items():
            model = getattr(contracts, name)
            schema = Draft202012Validator(model.model_json_schema())
            compact = Draft202012Validator(
                contracts.compact_schema(model.model_json_schema(), output=True))
            for original in records:
                with self.subTest(model=name, keys=sorted(original)):
                    record = {**copy.deepcopy(original), "extension": {"preserved": [1, None]}}
                    schema.validate(record)
                    compact.validate(record)
                    self.assertEqual(model.model_validate(record).model_dump(mode="json"), record)
            with self.subTest(model=name), self.assertRaises(ValidationError):
                model.model_validate({})
            self.assertFalse(schema.is_valid({}))
            self.assertFalse(compact.is_valid({}))

    def test_required_variant_fields_and_scalar_types_are_enforced(self):
        for record in [object_info(name=None), object_info(vertices="many")]:
            with self.subTest(record=record), self.assertRaises(ValidationError):
                contracts.ObjectEditResult.model_validate(record)
            self.assertFalse(Draft202012Validator(contracts.ObjectEditResult.model_json_schema()).is_valid(record))
        with self.assertRaises(ValidationError):
            contracts.ScatterResult.model_validate({**cases()["ScatterResult"][0], "estimated_instances": True})


class NativeScalarAndListCompatibility(unittest.TestCase):
    def test_separation_requires_its_metadata_and_preserves_part_records(self):
        model = contracts.MeshEditResult
        record = next(r for r in cases()["MeshEditResult"] if r.get("by") == "materials")
        self.assertEqual(model.model_validate(record).model_dump(mode="json"), record)
        schemas = [model.model_json_schema(),
                   contracts.compact_schema(model.model_json_schema(), output=True)]
        malformed = [{k: v for k, v in record.items() if k != missing}
                     for missing in ("source", "by", "count", "parts", "triangles_before")]
        malformed += [{**record, **change} for change in (
            {"by": "faces"}, {"parts": ["Prop"]}, {"count": True}, {"triangles_before": "24"})]
        for value in malformed:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError):
                    model.model_validate(value)
                for schema in schemas:
                    self.assertFalse(Draft202012Validator(schema).is_valid(value))

    def test_scene_collections_keep_homogeneous_name_or_detail_lists(self):
        model = contracts.SceneInfo
        for record in [object_info(collections=["Collection"]),
                       {"version": "5.2.3", "objects": [object_info()],
                        "collections": [{"name": "Collection", "objects": 1}]}]:
            self.assertEqual(model.model_validate(record).model_dump(mode="json"), record)
            for schema in [model.model_json_schema(),
                           contracts.compact_schema(model.model_json_schema(), output=True)]:
                Draft202012Validator(schema).validate(record)
        for collections in ([1], ["Collection", {"name": "Other"}]):
            with self.subTest(collections=collections), self.assertRaises(ValidationError):
                contracts.SceneInfo.model_validate(object_info(collections=collections))

    def test_deformation_list_and_texel_resolution_match_native_returns(self):
        inspection = {**cases()["RigInspection"][0],
                      "analyzed_action": "Walk", "animation_checks": {
                          "deformation": [{"name": "Body", "frames": []}],
                          "root_motion": {"bone": "Root"}}}
        edit = object_info(texture_resolution=1024)
        for model, record in [(contracts.RigInspection, inspection),
                              (contracts.MeshEditResult, edit)]:
            self.assertEqual(model.model_validate(record).model_dump(mode="json"), record)
            Draft202012Validator(contracts.compact_schema(
                model.model_json_schema(), output=True)).validate(record)


class ImportTextureCountTests(unittest.TestCase):
    def test_import_texture_counts_and_export_receipts_both_validate(self):
        for textures in (0, 2, [{'path':'BaseColor.png','sha256':'f'*64}]):
            value={'path':'model.obj','textures':textures}
            self.assertEqual(contracts.AssetResult.model_validate(value).model_dump(),value)
