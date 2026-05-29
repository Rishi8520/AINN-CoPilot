from pydantic import BaseModel, Field
from typing import Optional

class SimulationRequest(BaseModel):
    scenario: str = Field(..., description="Must be 'normal_operation', 'handover_failure', or 'energy_optimization'")
    ue_count: int = Field(default=10, ge=1, le=50, description="Number of User Equipments to simulate")

class KPIMetrics(BaseModel):
    throughput_mbps: float = Field(..., description="Mean downstream throughput received by UEs")
    latency_ms: float = Field(..., description="Mean end-to-end network latency")
    packet_loss_percent: float = Field(..., description="Percentage of dropped packets")
    sinr_db: float = Field(..., description="Average Signal-to-Interference-plus-Noise Ratio")
    handover_success_rate: float = Field(..., description="Ratio of successful handovers over total attempts")
    energy_saved_percent: float = Field(..., description="Energy savings achieved relative to baseline")

class SimulationResponse(BaseModel):
    status: str
    scenario: str
    ue_count: int
    cached: bool
    metrics: KPIMetrics
