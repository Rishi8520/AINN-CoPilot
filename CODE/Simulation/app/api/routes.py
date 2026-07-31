import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.schemas import SimulationRequest, SimulationResponse
from app.simulator.mode_config import get_mode_settings
from app.simulator.readiness import build_capabilities
from app.simulator.replay_service import (
    REPLAY_SCENARIO_ALIASES,
    ReplayError,
    ReplayFixtureService,
    resolve_replay_fixture_for_scenario,
)
from app.simulator.timeline_runner import TimelineRunner

router = APIRouter()
logger = logging.getLogger(__name__)

# Single shared, long-running runner for the whole process.
# Manages the real sequence of Simu5G subprocess phases.
runner = TimelineRunner(loop=True)
replay_service = ReplayFixtureService()


class RemediationRequest(BaseModel):
    gnb_id: int
    action: str = Field(..., description="e.g. traffic_steering | power_boost | activate_backup_power | restart_cell")
    detail: Optional[str] = ""


@router.get("/health")
def health():
    return {
        "backend": "UP",
        "process_liveness": True,
        "service": "simulation",
        "note": "Liveness only. Use /ready or /capabilities for replay/live availability.",
    }


@router.get("/ready")
def ready(response: Response):
    settings = get_mode_settings()
    capabilities = build_capabilities(settings, replay_service, runner=runner)
    response.status_code = 200 if capabilities["default_mode_available"] else 503
    return capabilities


@router.get("/capabilities")
def capabilities():
    settings = get_mode_settings()
    return build_capabilities(settings, replay_service, runner=runner)


@router.post("/start")
def start():
    settings = get_mode_settings()
    if not settings.live_enabled:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "live_mode_disabled",
                "message": "Set SIMULATION_LIVE_ENABLED=true before starting the live timeline runner.",
            },
        )
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


def _compatibility_note() -> str:
    return (
        "POST /simulate also accepts the older query-parameter form. "
        "When both JSON and query parameters are supplied, the JSON body is used."
    )


def _request_dict(request: SimulationRequest, mode: str) -> Dict[str, Any]:
    data = request.dict()
    data["mode"] = mode
    return data


def _unsupported_replay_parameters(request: SimulationRequest) -> Dict[str, str]:
    unsupported = {
        "ue_count": "Replay uses a recorded fixture; requested ue_count does not alter recorded output.",
        "cell_id": "Replay uses a recorded fixture; requested cell_id is accepted only as metadata.",
        "slice_type": "Replay uses a recorded fixture; requested slice_type is accepted only as metadata.",
    }
    if request.seed is not None:
        unsupported["seed"] = "Replay uses a recorded fixture; requested seed does not alter recorded output."
    return unsupported


def _unsupported_live_parameters(request: SimulationRequest) -> Dict[str, str]:
    unsupported = {
        "scenario": "The current live TimelineRunner executes its own phase sequence; one-off scenario selection is not applied per request.",
        "ue_count": "The current live TimelineRunner controls UE count through its generated phase INI, not per-request ue_count.",
        "cell_id": "The current live TimelineRunner does not filter results by requested cell_id.",
        "slice_type": "The current live TimelineRunner does not apply slice-specific behavior per request.",
    }
    if request.seed is not None:
        unsupported["seed"] = "The current live TimelineRunner does not apply a per-request deterministic seed."
    return unsupported


def _live_failure_response(
    request: SimulationRequest,
    mode: str,
    code: str,
    message: str,
    details: Dict[str, Any],
    http_status: int,
) -> JSONResponse:
    response = SimulationResponse(
        run_id=f"live-{uuid4()}",
        status="failed",
        mode="live",
        requested_parameters=_request_dict(request, mode),
        applied_parameters={"mode": "live"},
        unsupported_parameters=_unsupported_live_parameters(request),
        metrics={},
        result_reference={
            "live_simulation": True,
            "replay_fallback_used": False,
            "no_silent_live_to_replay_fallback": True,
        },
        error={"code": code, "message": message, "details": details},
        compatibility=_compatibility_note(),
    )
    return JSONResponse(status_code=http_status, content=response.dict())


def _latest_phase_status() -> Dict[str, Any]:
    history = list(getattr(runner, "history", []) or [])
    latest = history[-1] if history else None
    if not latest:
        return {"status": "accepted", "metrics": {}, "phase": None, "error": None}
    aggregate = (latest.kpis or {}).get("aggregate", {})
    if latest.returncode != 0:
        return {
            "status": "failed",
            "metrics": {},
            "phase": latest.name,
            "error": {
                "code": "live_runner_phase_failed",
                "message": "The latest live Simulation phase failed.",
                "details": {"phase": latest.name, "returncode": latest.returncode},
            },
        }
    if not aggregate:
        return {
            "status": "failed",
            "metrics": {},
            "phase": latest.name,
            "error": {
                "code": "live_output_empty",
                "message": "The latest live Simulation phase ended but produced no parsed aggregate metrics.",
                "details": {"phase": latest.name},
            },
        }
    return {"status": "completed", "metrics": aggregate, "phase": latest.name, "error": None}


def _simulate_replay(request: SimulationRequest, mode: str) -> SimulationResponse:
    settings = get_mode_settings()
    fixture_id = resolve_replay_fixture_for_scenario(request.scenario, settings.replay_fixture)
    logger.info("simulation simulate selected mode=replay fixture_id=%s", fixture_id)
    replayed = replay_service.replay(
        fixture_id,
        strict_checksums=settings.replay_strict_checksums,
    )
    provenance = replayed["provenance"]
    return SimulationResponse(
        run_id=f"replay-{fixture_id}-{uuid4()}",
        status="completed",
        mode="replay",
        requested_parameters=_request_dict(request, mode),
        applied_parameters={
            "mode": "replay",
            "scenario_alias": request.scenario,
            "fixture_id": fixture_id,
            "scenario_fixture_mapping": {request.scenario: fixture_id},
        },
        unsupported_parameters=_unsupported_replay_parameters(request),
        metrics=replayed["metrics"],
        result_reference={
            "mode_label": "recorded_replay",
            "live_simulation": False,
            "provenance": provenance,
            "recorded_fixture_parameters": replayed["recorded_fixture_parameters"],
            "supported_replay_scenarios": sorted(REPLAY_SCENARIO_ALIASES),
        },
        error=None,
        compatibility=_compatibility_note(),
    )


def _simulate_live(request: SimulationRequest, mode: str) -> SimulationResponse | JSONResponse:
    settings = get_mode_settings()
    caps = build_capabilities(settings, replay_service, runner=runner)
    if not caps["live_enabled"]:
        logger.info("simulation live unavailable category=disabled")
        return _live_failure_response(
            request,
            mode,
            "live_mode_disabled",
            "Live Simulation mode is disabled. Set SIMULATION_LIVE_ENABLED=true to enable it.",
            {"missing_live_requirements": caps["missing_live_requirements"]},
            503,
        )
    if not caps["live_available"]:
        logger.info("simulation live unavailable category=missing_requirements")
        return _live_failure_response(
            request,
            mode,
            "live_mode_unavailable",
            "Live Simulation prerequisites are missing or unavailable.",
            {"missing_live_requirements": caps["missing_live_requirements"]},
            503,
        )

    logger.info("simulation simulate selected mode=live")
    if not runner.running:
        runner.start()
        return SimulationResponse(
            run_id=f"live-{uuid4()}",
            status="started",
            mode="live",
            requested_parameters=_request_dict(request, mode),
            applied_parameters={"mode": "live", "source": "timeline_runner_start"},
            unsupported_parameters=_unsupported_live_parameters(request),
            metrics={},
            result_reference={
                "live_simulation": True,
                "replay_fallback_used": False,
                "engine": "simu5g (real opp_run subprocess)",
            },
            error=None,
            compatibility=_compatibility_note(),
        )

    snap = runner.snapshot()
    phase = _latest_phase_status()
    if phase["status"] == "failed":
        status_value = "failed"
        error = phase["error"]
        metrics = {}
    else:
        status_value = phase["status"]
        error = None
        metrics = phase["metrics"]

    return SimulationResponse(
        run_id=f"live-{uuid4()}",
        status=status_value,
        mode="live",
        requested_parameters=_request_dict(request, mode),
        applied_parameters={
            "mode": "live",
            "source": "current_live_timeline_snapshot",
            "current_phase": snap["current_phase"],
        },
        unsupported_parameters=_unsupported_live_parameters(request),
        metrics=metrics,
        result_reference={
            "current_phase": snap["current_phase"],
            "last_completed_phase": phase["phase"],
            "engine": snap["engine"],
            "simulation_running": bool(snap["running"]),
            "simulation_time_s": snap["cumulative_sim_time_s"],
            "gnbs": len(snap["gnbs"]),
            "live_simulation": True,
            "replay_fallback_used": False,
            "no_silent_live_to_replay_fallback": True,
        },
        error=error,
        compatibility=_compatibility_note(),
    )


# ---------------- legacy compatibility ----------------
# Kept so existing agent tool-call integrations that expect POST /simulate
# keep working. JSON remains canonical and goes through the same mode dispatch.

@router.post("/simulate", response_model=SimulationResponse)
def simulate_compat(
    req: Optional[SimulationRequest] = Body(default=None),
    scenario: str = Query(default="normal_operation"),
    ue_count: int = Query(default=10, ge=1, le=100),
    cell_id: str = Query(default="0"),
    slice_type: str = Query(default="eMBB"),
    mode: Optional[str] = Query(default=None),
):
    request = req or SimulationRequest(
        scenario=scenario,
        ue_count=ue_count,
        cell_id=cell_id,
        slice_type=slice_type,
        mode=mode,
    )
    try:
        selected_mode = get_mode_settings().resolve_mode(request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        if selected_mode == "replay":
            return _simulate_replay(request, selected_mode)
        return _simulate_live(request, selected_mode)
    except ReplayError as exc:
        status_code = 400
        if exc.code in {"missing_manifest", "missing_fixture_file", "checksum_validation_failed", "fixture_parse_failed"}:
            status_code = 503
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": exc.message, "details": exc.details},
        ) from exc
