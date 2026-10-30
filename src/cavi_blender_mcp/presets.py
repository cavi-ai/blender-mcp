"""Engine axis and unit presets for Blender's FBX and USD exporters."""

AXIS_PRESETS = {
    # Native Z-up file; Unity bakeAxisConversion yields identity nodes, Y-up meshes.
    # bake_space_transform rotates empties under parented meshes.
    "unity": {"axis_forward": "Y", "axis_up": "Z", "apply_unit_scale": True,
              "apply_scale_options": "FBX_SCALE_UNITS", "bake_space_transform": False},
    # Z-up, X-forward; the FBX unit scale carries centimetres.
    "unreal": {"axis_forward": "X", "axis_up": "Z", "apply_unit_scale": True,
               "apply_scale_options": "FBX_SCALE_NONE", "bake_space_transform": False},
    "godot": {"axis_forward": "-Z", "axis_up": "Y", "apply_unit_scale": True,
              "apply_scale_options": "FBX_SCALE_ALL", "bake_space_transform": True},
}
USD_AXES = {"unity": ("NEGATIVE_Z", "Y"), "unreal": ("X", "Z"), "godot": ("NEGATIVE_Z", "Y")}
