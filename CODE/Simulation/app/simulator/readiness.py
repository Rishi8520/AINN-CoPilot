import os
from pathlib import Path
from typing import Any, Dict, List

from app.simulator.mode_config import SimulationModeSettings
from app.simulator.replay_service import ReplayError, ReplayFixtureService
from app.simulator.timeline_runner import (
    GENERATED_DIR,
    NED_PATH,
    OPP_RUN,
    OPP_RUN_CWD,
    RESULTS_DIR,
    SCENARIOS_DIR,
    SIMU5G_LIBS,
)


def _path_exists(path: str) -> bool:
    return bool(path) and Path(path).exists()


def _is_executable(path: str) -> bool:
    return _path_exists(path) and os.access(path, os.X_OK)


def _writable_dir(path: str) -> bool:
    directory = Path(path)
    return directory.exists() and directory.is_dir() and os.access(directory, os.W_OK)


def probe_live_requirements(settings: SimulationModeSettings, runner: Any = None) -> Dict[str, Any]:
    missing: List[Dict[str, str]] = []
    warnings: List[str] = []

    if not settings.live_enabled:
        missing.append({
            "component": "mode",
            "requirement": "SIMULATION_LIVE_ENABLED=true",
            "status": "disabled",
        })

    if not _is_executable(OPP_RUN):
        missing.append({
            "component": "opp_run",
            "requirement": "configured OPP_RUN_BIN must exist and be executable",
            "status": "missing_or_not_executable",
        })

    if not _path_exists(OPP_RUN_CWD):
        missing.append({
            "component": "opp_run_cwd",
            "requirement": "configured OPP_RUN_CWD must exist",
            "status": "missing",
        })

    for name, path in [("INET_LIB", SIMU5G_LIBS[0]), ("SIMU5G_LIB", SIMU5G_LIBS[1])]:
        if not _path_exists(path):
            missing.append({
                "component": name.lower(),
                "requirement": f"{name} must point to an available shared library",
                "status": "missing",
            })

    ned_entries = [entry for entry in NED_PATH.split(":") if entry]
    missing_ned_entries = [entry for entry in ned_entries if not _path_exists(entry)]
    if missing_ned_entries:
        missing.append({
            "component": "ned_path",
            "requirement": "all configured SIMU5G_NED_PATH entries must exist",
            "status": f"{len(missing_ned_entries)}_missing_entries",
        })

    for filename in ["_topology_include.ini", "TelcoMindNetwork.ned", "TelcoNetTopology.ned"]:
        if not (Path(SCENARIOS_DIR) / filename).exists():
            missing.append({
                "component": "scenario_assets",
                "requirement": f"{filename} must exist",
                "status": "missing",
            })

    for label, path in [("generated_dir", GENERATED_DIR), ("results_dir", RESULTS_DIR)]:
        if not _writable_dir(path):
            missing.append({
                "component": label,
                "requirement": "runtime directory must be writable",
                "status": "not_writable",
            })

    if runner is None:
        warnings.append("runner object was not supplied to readiness probe")

    return {
        "live_enabled": settings.live_enabled,
        "live_available": settings.live_enabled and not missing,
        "missing_live_requirements": missing,
        "warnings": warnings,
    }


def build_capabilities(
    settings: SimulationModeSettings,
    replay_service: ReplayFixtureService,
    runner: Any = None,
) -> Dict[str, Any]:
    replay_status: Dict[str, Any]
    try:
        replay_validation = replay_service.validate_fixture(
            settings.replay_fixture,
            strict_checksums=settings.replay_strict_checksums,
        )
        replay_status = {
            "available": True,
            "fixture_id": replay_validation["fixture_id"],
            "checksums_verified": replay_validation["checksums_verified"],
            "source_artifacts": replay_validation["source_artifacts"],
        }
    except ReplayError as exc:
        replay_status = {
            "available": False,
            "fixture_id": settings.replay_fixture,
            "error": {"code": exc.code, "message": exc.message, "details": exc.details},
        }

    live = probe_live_requirements(settings, runner=runner)
    default_available = replay_status["available"] if settings.default_mode == "replay" else live["live_available"]

    return {
        "default_mode": settings.default_mode,
        "default_mode_available": default_available,
        "replay_available": replay_status["available"],
        "replay": replay_status,
        "live_enabled": live["live_enabled"],
        "live_available": live["live_available"],
        "missing_live_requirements": live["missing_live_requirements"],
        "warnings": live["warnings"],
        "fixture_ids": [settings.replay_fixture] if replay_status["available"] else [],
        "accepted_modes": ["replay", "live"],
        "no_silent_live_to_replay_fallback": True,
    }
