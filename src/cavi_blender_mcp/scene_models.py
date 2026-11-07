"""Reproducible camera, lighting, environment and production render definitions."""

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
type Positive = Annotated[Number, Field(gt=0)]
Vector = tuple[Number, Number, Number]
type Name = Annotated[str, Field(min_length=1, max_length=63)]


class Definition(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SurfaceRay(Definition):
    origin_world: Vector
    direction_world: Vector
    max_distance_m: Positive
    evaluated: StrictBool = False

    @model_validator(mode='after')
    def nonzero_direction(self):
        if not 0 < math.hypot(*self.direction_world) < math.inf:
            raise ValueError('Surface ray direction must be nonzero and finite')
        return self


class CameraRay(Definition):
    camera: Name
    pixel: tuple[Number, Number]
    image_size: tuple[Annotated[StrictInt, Field(gt=0)], Annotated[StrictInt, Field(gt=0)]]
    max_distance_m: Positive
    evaluated: StrictBool = False
    expected_projection_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$')] = None
    expected_geometry_sha256: Annotated[str | None, Field(pattern='^[0-9a-f]{64}$')] = None

    @model_validator(mode='after')
    def inside_image(self):
        if any(not 0 <= p <= size-1 for p,size in zip(self.pixel,self.image_size,strict=True)):
            raise ValueError('Camera pixel must lie within the declared image')
        return self


class CameraSpec(Definition):
    name: Name
    location: Vector
    target: Vector
    projection: Literal['perspective', 'orthographic'] = 'perspective'
    focal_length_mm: Positive = 50
    sensor_width_mm: Positive = 36
    ortho_scale: Positive = 10
    clip_start: Positive = .01
    clip_end: Positive = 1000
    shift: tuple[Number, Number] = (0, 0)
    depth_of_field: StrictBool = False
    fstop: Positive = 2.8
    focus_distance: Positive = 10


class LightSpec(Definition):
    name: Name
    type: Literal['AREA', 'POINT', 'SUN', 'SPOT'] = 'AREA'
    location: Vector
    target: Vector | None = None
    energy: Annotated[Number, Field(ge=0)]
    color: Vector = (1, 1, 1)
    size: Positive = 2
    size_y: Positive = 2
    shape: Literal['SQUARE', 'RECTANGLE', 'DISK', 'ELLIPSE'] = 'DISK'
    radius: Annotated[Number, Field(ge=0)] = .1
    angle_degrees: Annotated[Number, Field(gt=0, le=180)] = .526
    spot_size_degrees: Annotated[Number, Field(gt=0, le=180)] = 45
    spot_blend: Annotated[Number, Field(ge=0, le=1)] = .15


class WorldSpec(Definition):
    name: Name
    color: Vector = (.05, .05, .05)
    strength: Annotated[Number, Field(ge=0)] = 1
    hdri: str | None = None
    rotation_degrees: Vector = (0, 0, 0)


class PreviewSettings(Definition):
    display_device: Annotated[str, Field(min_length=1, max_length=64)] = 'sRGB'
    view_transform: Annotated[str, Field(min_length=1, max_length=64)] = 'AgX'
    look: Annotated[str, Field(min_length=1, max_length=64)] = 'None'
    exposure: Number = 0
    gamma: Positive = 1
    bit_depth: Literal['8', '16'] = '16'
    use_curve_mapping: StrictBool = False
    use_white_balance: StrictBool = False
    use_compositing: StrictBool = False


class RenderSpec(Definition):
    path: str
    camera: Name
    engine: Literal['cycles', 'eevee'] = 'cycles'
    device: Literal['CPU', 'GPU'] = 'CPU'
    width: Annotated[StrictInt, Field(ge=1, le=65536)] = 1920
    height: Annotated[StrictInt, Field(ge=1, le=65536)] = 1080
    samples: Annotated[StrictInt, Field(ge=1, le=1048576)] = 128
    file_format: Literal['png', 'exr', 'tiff'] = 'png'
    bit_depth: Literal['8', '16', '32'] = '16'
    transparent: StrictBool = False
    view_transform: Annotated[str, Field(min_length=1, max_length=64)] = 'AgX'
    exposure: Number = 0
    gamma: Positive = 1
    denoise: StrictBool = True
    frame: Annotated[StrictInt | None, Field(ge=1, le=1000000)] = None
    threads: Annotated[StrictInt, Field(ge=1, le=1024)] = 2
    cycles_time_limit: Annotated[Number, Field(ge=0)] = 120
    max_pixels: Annotated[StrictInt, Field(ge=1, le=4294967296)] = 16777216

    @model_validator(mode='after')
    def validate_output(self):
        if self.width*self.height > self.max_pixels:
            raise ValueError('Requested dimensions exceed max_pixels')
        if self.bit_depth not in {'png': {'8', '16'}, 'exr': {'16', '32'},
                                  'tiff': {'8', '16'}}[self.file_format]:
            raise ValueError('Bit depth does not match the output format')
        return self
