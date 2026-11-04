"""NLA strip settings shared by host validation and Blender's native adapter."""

import math

NUMBERS = {'frame_start': (None, None), 'action_frame_start': (None, None),
           'action_frame_end': (None, None), 'scale': (.0001, 1000), 'repeat': (.1, 1000),
           'blend_in': (0, None), 'blend_out': (0, None), 'influence': (0, 1)}
BOOLEANS = {'mute', 'use_reverse', 'use_auto_blend', 'use_animated_influence'}
ENUMS = {'blend_type': {'REPLACE', 'COMBINE', 'ADD', 'SUBTRACT', 'MULTIPLY'},
         'extrapolation': {'NOTHING', 'HOLD', 'HOLD_FORWARD'}}
FIELDS = tuple(NUMBERS) + tuple(sorted(BOOLEANS)) + tuple(ENUMS)


def validate(value):
    if not isinstance(value, dict) or not value or set(value) - set(FIELDS):
        raise ValueError('strip_settings needs at least one supported NLA setting')
    for key, item in value.items():
        if key in NUMBERS:
            low, high = NUMBERS[key]
            if (type(item) not in (int, float) or not math.isfinite(item)
                    or low is not None and item < low or high is not None and item > high):
                raise ValueError('Invalid finite NLA setting: ' + key)
        elif key in BOOLEANS and type(item) is not bool:
            raise ValueError('NLA setting must be boolean: ' + key)
        elif key in ENUMS and (not isinstance(item, str) or item not in ENUMS[key]):
            raise ValueError('Unknown NLA setting: ' + key)
    if ('action_frame_start' in value and 'action_frame_end' in value
            and value['action_frame_end'] <= value['action_frame_start']):
        raise ValueError('NLA action frame range must increase')
    if value.get('use_auto_blend') and {'blend_in', 'blend_out'} & set(value):
        raise ValueError('Automatic blending computes fades; omit manual blend_in/blend_out')
    return value
