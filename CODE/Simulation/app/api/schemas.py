from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, validator


SUPPORTED_SCENARIOS = {
    "baseline",
    "normal",
    "normal_operation",
    "bootstrap_normal",
    "phase_bootstrap_normal",
    "handover_stress",
    "handover_failure",
    "energy_saving",
    "energy_optimization",
    "high_load",
    "interference_high",
    "hotspot_traffic_burst",
}
SUPPORTED_SLICE_TYPES = {"eMBB", "URLLC", "mMTC"}


class StrictBaseModel(BaseModel):
    class Config:
        extra = "forbid"


class SimulationRequest(StrictBaseModel):
    scenario: str = Field(
        default="normal_operation",
        min_length=1,
        description=(
            "normal_operation | handover_failure | energy_optimization | "
            "hotspot_traffic_burst"
        ),
    )
    ue_count: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Number of UEs requested by the caller.",
    )
    cell_id: Union[int, str] = Field(
        default=0,
        description=(
            "Target gNB/cell identifier such as 0 or cell-1. "
            "Accepted as metadata in Batch 3."
        ),
    )
    slice_type: str = Field(
        default="eMBB",
        description="eMBB | URLLC | mMTC. Accepted as metadata in Batch 3.",
    )
    seed: Optional[int] = Field(
        default=None,
        ge=0,
        description="Optional deterministic seed. Accepted as metadata unless a mode explicitly supports it.",
    )
    mode: Optional[Literal["live", "replay"]] = Field(
        default=None,
        description="Requested execution mode. If omitted, SIMULATION_DEFAULT_MODE is used.",
    )

    @validator("scenario")
    def scenario_must_be_supported(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in SUPPORTED_SCENARIOS:
            raise ValueError(f"Unsupported scenario: {value}")
        return normalized

    @validator("cell_id")
    def cell_id_must_be_nonempty_metadata(cls, value: Union[int, str]) -> Union[int, str]:
        if isinstance(value, int):
            if value < 0:
                raise ValueError("cell_id must be non-negative")
            return value
        normalized = value.strip()
        if not normalized:
            raise ValueError("cell_id must not be empty")
        return normalized

    @validator("slice_type")
    def slice_type_must_be_supported(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in SUPPORTED_SLICE_TYPES:
            raise ValueError(f"Unsupported slice_type: {value}")
        return normalized


class PolicyRequest(StrictBaseModel):
    sector_id: str = Field(
        ...,
        description="Example: gNB_0_Sec_0"
    )

    policy_type: str = Field(
        ...,
        description="deep_sleep | power_trim"
    )


class SimulationResponse(StrictBaseModel):
    run_id: str
    status: Literal["accepted", "started", "completed", "failed", "unsupported", "timeout"]
    mode: Literal["live", "replay"]
    requested_parameters: Dict[str, Any]
    applied_parameters: Dict[str, Any]
    unsupported_parameters: Dict[str, str] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    result_reference: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[Dict[str, Any]] = None
    compatibility: Optional[str] = None


class LegacySimulationResponse(BaseModel):
    status: str
    scenario: str
    ue_count: int
    cached: bool
    metrics: Dict
