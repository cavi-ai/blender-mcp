"""Host-side contracts for constraints and precise skin weights."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

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
