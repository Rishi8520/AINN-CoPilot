from pydantic import BaseModel, Field
from typing import Dict


class SimulationRequest(BaseModel):
    scenario: str = Field(
        ...,
        description="normal_operation | handover_failure | energy_optimization"
    )

    ue_count: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of UEs"
    )

    slice_type: str = Field(
        default="eMBB",
        description="eMBB | URLLC | mMTC"
    )


class PolicyRequest(BaseModel):
    sector_id: str = Field(
        ...,
        description="Example: gNB_0_Sec_0"
    )

    policy_type: str = Field(
        ...,
        description="deep_sleep | power_trim"
    )


class SimulationResponse(BaseModel):
    status: str
    scenario: str
    ue_count: int
    cached: bool
    metrics: Dict