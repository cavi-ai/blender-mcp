"""Engine axis and unit presets for Blender's FBX and USD exporters."""

AXIS_PRESETS = {
    # Y-up, model front +Z, metre units baked into transforms.
    "unity": {"axis_forward": "-Z", "axis_up": "Y", "apply_unit_scale": True,
              "apply_scale_options": "FBX_SCALE_UNITS", "bake_space_transform": True},
    # Z-up, X-forward; the FBX unit scale carries centimetres.
    "unreal": {"axis_forward": "X", "axis_up": "Z", "apply_unit_scale": True,
               "apply_scale_options": "FBX_SCALE_NONE", "bake_space_transform": False},
    "godot": {"axis_forward": "-Z", "axis_up": "Y", "apply_unit_scale": True,
              "apply_scale_options": "FBX_SCALE_ALL", "bake_space_transform": True},
}
USD_AXES = {"unity": ("NEGATIVE_Z", "Y"), "unreal": ("X", "Z"), "godot": ("NEGATIVE_Z", "Y")}
