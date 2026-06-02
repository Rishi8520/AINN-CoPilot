from fastapi import APIRouter, HTTPException
from app.api.schemas import SimulationRequest, PolicyRequest
from app.simulator.simu5g_runner import Simu5GRunner
from app.simulator.kpi_parser import KPIParser

router = APIRouter()
runner = Simu5GRunner()

SCENARIO_ALIASES = {
    "baseline": "normal_operation",
    "normal_operation": "normal_operation",

    "handover_stress": "handover_failure",
    "handover_failure": "handover_failure",

    "energy_saving": "energy_optimization",
    "energy_optimization": "energy_optimization",

    "high_load": "hotspot_traffic_burst",
    "interference_high": "hotspot_traffic_burst",
    "hotspot_traffic_burst": "hotspot_traffic_burst",
}

SUPPORTED_SCENARIOS = set(SCENARIO_ALIASES.values())

@router.get("/scenarios")
async def list_scenarios():
    return {
        "supported_scenarios": sorted(SUPPORTED_SCENARIOS),
        "aliases": SCENARIO_ALIASES,
        "slice_types": ["eMBB", "URLLC", "mMTC"]
    }

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
    mapped_scenario = SCENARIO_ALIASES.get(payload.scenario, payload.scenario)

    if mapped_scenario not in SUPPORTED_SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "Unsupported scenario",
                "requested": payload.scenario,
                "supported": sorted(SUPPORTED_SCENARIOS),
            },
        )

    raw_data = runner.run(mapped_scenario, payload.ue_count)

    metrics = raw_data["metrics"]

    if payload.slice_type == "URLLC":
        metrics["latency_ms"] = round(max(1.0, metrics["latency_ms"] * 0.2), 2)
        metrics["packet_loss_percent"] = round(min(0.1, metrics["packet_loss_percent"] * 0.1), 2)
    elif payload.slice_type == "mMTC":
        metrics["throughput_mbps"] = round(metrics["throughput_mbps"] * 0.3, 2)
        metrics["latency_ms"] = round(metrics["latency_ms"] * 1.5, 2)

    return {
        "status": "success",
        "requested_scenario": payload.scenario,
        "scenario": mapped_scenario,
        "ue_count": payload.ue_count,
        "cell_id": payload.cell_id,
        "slice_type": payload.slice_type,
        "data": raw_data,
    }

@router.post("/policy")
async def apply_network_policy(payload: PolicyRequest):
    result = KPIParser.apply_policy(payload.sector_id, payload.policy_type)
    return result
