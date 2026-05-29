from fastapi import APIRouter
from pydantic import BaseModel
from app.simulator.simu5g_runner import Simu5GRunner
from app.simulator.kpi_parser import KPIParser

router = APIRouter()
runner = Simu5GRunner()

class SimulationRequest(BaseModel):
    scenario: str
    ue_count: int
    slice_type: str = "eMBB"  # eMBB, URLLC, or mMTC

class PolicyRequest(BaseModel):
    sector_id: str
    policy_type: str

@router.get("/status")
async def get_system_status():
    """Provides the current network health for RAG/AI agents."""
    return {
        "status": "active",
        "active_policies": KPIParser._active_policies,
        "cluster_info": "7-Cell Hexagonal Cluster"
    }

@router.post("/simulate")
async def execute_simulation(payload: SimulationRequest):
    # Retrieve raw metrics from the parser
    raw_data = runner.run(payload.scenario, payload.ue_count)
    
    # Adjust latency and loss based on Slice Type (Closed-loop logic)
    metrics = raw_data["metrics"]
    if payload.slice_type == "URLLC":
        metrics["latency_ms"] = max(1.0, metrics["latency_ms"] * 0.2)
        metrics["packet_loss_percent"] = min(0.1, metrics["packet_loss_percent"] * 0.1)
    elif payload.slice_type == "mMTC":
        metrics["throughput_mbps"] = metrics["throughput_mbps"] * 0.3
        metrics["latency_ms"] = metrics["latency_ms"] * 1.5
    
    return {
        "status": "success",
        "scenario": payload.scenario,
        "ue_count": payload.ue_count,
        "slice_type": payload.slice_type,
        "data": raw_data
    }

@router.post("/policy")
async def apply_network_policy(payload: PolicyRequest):
    result = KPIParser.apply_policy(payload.sector_id, payload.policy_type)
    return result
