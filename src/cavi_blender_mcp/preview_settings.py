"""Observe and temporarily override display controls without editing their curves or nodes."""

import math
from contextlib import contextmanager

VIEW_FIELDS = ('view_transform', 'look', 'exposure', 'gamma', 'use_curve_mapping', 'use_white_balance')
FLAGS = ('use_curve_mapping', 'use_white_balance', 'use_compositing')


def snapshot(scene):
    result = {name: getattr(scene.view_settings, name, None) for name in VIEW_FIELDS}
    output = scene.render.image_settings
    return {**result, 'display_device': scene.display_settings.display_device, 'use_compositing': scene.render.use_compositing,
            'file_format': output.file_format, 'color_mode': output.color_mode, 'bit_depth': output.color_depth}


def validate(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {*VIEW_FIELDS, 'display_device', 'bit_depth', 'use_compositing'}:
        raise ValueError('Preview settings require the complete typed definition')
    for name in ('display_device', 'view_transform', 'look'):
        if not isinstance(value[name], str) or not 1 <= len(value[name]) <= 64:
            raise ValueError('Preview ' + name + ' must name an available display setting')
    for name in ('exposure', 'gamma'):
        if type(value[name]) not in (int, float) or not math.isfinite(value[name]):
            raise ValueError('Preview ' + name + ' must be finite')
    if value['gamma'] <= 0 or value['bit_depth'] not in {'8', '16'}:
        raise ValueError('Preview gamma must be positive and PNG depth must be 8 or 16')
    if any(type(value[name]) is not bool for name in FLAGS):
        raise ValueError('Preview curve, white-balance and compositing toggles must be boolean')
    return dict(value)


@contextmanager
def configured(scene, settings):
    if settings is None:
        yield
        return
    view = scene.view_settings
    original = snapshot(scene)
    if original['use_white_balance'] is None and settings['use_white_balance']:
        raise ValueError('This Blender runtime does not expose display white balance')
    try:
        scene.display_settings.display_device = settings['display_device']
        for name in VIEW_FIELDS:
            if name == 'use_white_balance' and original[name] is None:
                continue
            setattr(view, name, settings[name])
            actual = getattr(view, name)
            if name in {'exposure', 'gamma'} and not math.isclose(actual, settings[name], rel_tol=1e-6, abs_tol=1e-6):
                raise ValueError('Preview ' + name + ' exceeds the native display range')
        scene.render.use_compositing = settings['use_compositing']
        yield
    finally:
        # The transform controls which looks are available, so restore it first.
        scene.display_settings.display_device = original['display_device']
        for name in VIEW_FIELDS:
            if original[name] is not None:
                setattr(view, name, original[name])
        scene.render.use_compositing = original['use_compositing']
