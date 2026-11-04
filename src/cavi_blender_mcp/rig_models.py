"""Host-side contracts for constraints and precise skin weights."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector = tuple[Number, Number, Number]
Name = Annotated[str, Field(min_length=1, max_length=63)]


class ConstraintSpec(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: Name
    bone: Name
    influence: Annotated[Number, Field(ge=0, le=1)] = 1


class IKConstraintSpec(ConstraintSpec):
    type: Literal['IK'] = 'IK'
    target: Name
    subtarget: Name | None = None
    pole_target: Name | None = None
    pole_subtarget: Name | None = None
    pole_angle_degrees: Number = 0
    chain_count: Annotated[StrictInt, Field(ge=0, le=255)] = 2
    iterations: Annotated[StrictInt, Field(ge=1, le=10000)] = 500
    use_tail: StrictBool = True
    use_stretch: StrictBool = True


class LimitRotationSpec(ConstraintSpec):
    type: Literal['LIMIT_ROTATION'] = 'LIMIT_ROTATION'
    minimum_degrees: Vector
    maximum_degrees: Vector
    axes: tuple[StrictBool, StrictBool, StrictBool] = (True, True, True)
    owner_space: Literal['WORLD', 'POSE', 'LOCAL', 'LOCAL_WITH_PARENT'] = 'LOCAL'


Constraint = Annotated[IKConstraintSpec | LimitRotationSpec, Field(discriminator='type')]


class VertexWeights(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vertex: Annotated[StrictInt, Field(ge=0)]
    weights: Annotated[dict[Name, Annotated[Number, Field(ge=0, le=1)]], Field(max_length=512)]


class MotionSkinPair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source: Name
    candidate: Name


class RetargetCalibration(BaseModel):
    model_config = ConfigDict(extra='forbid')
    root: Name
    root_translation_scale: Annotated[Number, Field(gt=0)]
    alignment_degrees: Vector = (0, 0, 0)


class ContactWindow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bone: Name
    point: Vector
    start_frame: Annotated[StrictInt, Field(ge=1, le=1000000)]
    end_frame: Annotated[StrictInt, Field(ge=1, le=1000000)]
    samples: Annotated[StrictInt, Field(ge=2, le=32)] = 9
    max_drift_m: Annotated[Number, Field(ge=0)]
    max_height_error_m: Annotated[Number, Field(ge=0)]
    ground_z_m: Number

    @model_validator(mode='after')
    def increasing(self):
        if self.end_frame <= self.start_frame:
            raise ValueError('Contact windows need an increasing frame range')
        return self


class FootLockWindow(ContactWindow):
    pole: Vector
    pole_angle_degrees: Number = 0
    blend_in_frames: Annotated[StrictInt, Field(ge=1, le=1000)] = 3
    blend_out_frames: Annotated[StrictInt, Field(ge=1, le=1000)] = 3
