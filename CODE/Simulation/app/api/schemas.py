from pydantic import BaseModel, Field
from typing import Optional, Literal
class SimulationRequest(BaseModel):
    scenario: str = Field(
        ...,
        description="Scenario name or alias: normal_operation, handover_failure, energy_optimization, hotspot_traffic_burst"
    )
    ue_count: int = Field(default=10, ge=1, le=100)
    cell_id: Optional[int] = Field(default=0)
    slice_type: Literal["eMBB", "URLLC", "mMTC"] = "eMBB"
class PolicyRequest(BaseModel):
    sector_id: str
    policy_type: Literal["deep_sleep", "power_trim", "normal"]
class KPIMetrics(BaseModel):
    throughput_mbps: float = Field(..., description="Mean downstream throughput received by UEs")
    latency_ms: float = Field(..., description="Mean end-to-end network latency")
    packet_loss_percent: float = Field(..., description="Percentage of dropped packets")
    sinr_db: float = Field(..., description="Average Signal-to-Interference-plus-Noise Ratio")
    handover_success_rate: float = Field(..., description="Ratio of successful handovers over total attempts")
    energy_saved_percent: float = Field(..., description="Energy savings achieved relative to baseline")

class SimulationResponse(BaseModel):
    status: str
    requested_scenario: str
    scenario: str
    ue_count: int
    cell_id: int
    slice_type: str
    data: dict