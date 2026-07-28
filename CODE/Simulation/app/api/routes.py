from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from app.simulator.timeline_runner import TimelineRunner

router = APIRouter()

# Single shared, long-running runner for the whole process.
# Manages the real sequence of Simu5G subprocess phases.
runner = TimelineRunner(loop=True)


class RemediationRequest(BaseModel):
    gnb_id: int
    action: str = Field(..., description="e.g. traffic_steering | power_boost | activate_backup_power | restart_cell")
    detail: Optional[str] = ""


@router.get("/health")
def health():
    snap = runner.snapshot()
    return {
        "backend": "UP",
        "simulation": "RUNNING" if snap["running"] else "STOPPED",
        "engine": snap["engine"],
        "current_phase": snap["current_phase"],
        "simulationTime": snap["cumulative_sim_time_s"],
        "gnbs": len(snap["gnbs"]),
    }


@router.post("/start")
def start():
    runner.start()
    return {"status": "started", "engine": "simu5g (real opp_run subprocess loop)"}


@router.post("/stop")
def stop():
    runner.stop()
    return {"status": "stopped", "cumulative_sim_time_s": runner.cumulative_sim_time}


@router.get("/status")
def status():
    return runner.snapshot()


@router.get("/gnb/{gnb_id}")
def gnb_detail(gnb_id: int):
    detail = runner.gnb_snapshot(gnb_id)
    if not detail:
        raise HTTPException(status_code=404, detail="gNB not found")
    return detail


@router.post("/remediate")
def remediate(req: RemediationRequest):
    """
    Records a remediation request against a gNB. Applied at the next
    phase boundary (see TimelineRunner.request_remediation for why —
    OMNeT++ has no supported live mid-run parameter API).
    """
    if not req.gnb_id in runner.gnb_ids:
        raise HTTPException(status_code=404, detail="gNB not found")
    runner.request_remediation(req.gnb_id, req.action, detail=req.detail or "")
    return {"status": "recorded", "gnb_id": req.gnb_id, "action": req.action,
            "applies_at": "next phase boundary"}


# ---------------- legacy compatibility ----------------
# Kept so existing agent tool-call integrations (Member 3's tools.yaml)
# that expect POST /simulate keep working. Returns the current real
# timeline snapshot instead of launching an isolated one-off run.

@router.post("/simulate")
def simulate_compat(scenario: str = "normal_operation", ue_count: int = 10, slice_type: str = "eMBB"):
    snap = runner.snapshot()
    return {
        "status": "success",
        "note": "Legacy endpoint: returns the live real-Simu5G timeline snapshot.",
        "requested_scenario": scenario,
        "current_phase": snap["current_phase"],
        "metrics": snap["last_completed_phase_kpis"].get("aggregate", {}),
        "live_status": snap,
    }
