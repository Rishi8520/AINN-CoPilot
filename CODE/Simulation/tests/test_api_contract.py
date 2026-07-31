import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError


SIM_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_ROOT))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        sys.modules.pop(module_name, None)

from app.api import routes  # noqa: E402
from app.api.schemas import SimulationRequest  # noqa: E402
from app.simulator.replay_service import REPLAY_SCENARIO_ALIASES  # noqa: E402


@pytest.fixture(autouse=True)
def simulation_env(monkeypatch):
    monkeypatch.setenv("SIMULATION_DEFAULT_MODE", "replay")
    monkeypatch.setenv("SIMULATION_REPLAY_FIXTURE", "phase_bootstrap_normal")
    monkeypatch.setenv("SIMULATION_REPLAY_STRICT_CHECKSUMS", "true")
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "false")


def test_simulation_request_accepts_canonical_json_fields():
    req = SimulationRequest(
        scenario="baseline",
        ue_count=20,
        cell_id="cell-1",
        slice_type="eMBB",
        seed=42,
        mode="live",
    )

    assert req.scenario == "baseline"
    assert req.ue_count == 20
    assert req.cell_id == "cell-1"
    assert req.slice_type == "eMBB"
    assert req.seed == 42


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario": "normal_operation", "ue_count": 0},
        {"scenario": "normal_operation", "ue_count": 101},
        {"scenario": "normal_operation", "cell_id": -1},
        {"scenario": "normal_operation", "mode": "batch"},
        {"scenario": "unsupported_scenario"},
        {"scenario": "normal_operation", "slice_type": "video"},
        {"scenario": "normal_operation", "unexpected": True},
    ],
)
def test_simulation_request_rejects_malformed_fields(payload):
    with pytest.raises(ValidationError):
        SimulationRequest(**payload)


def test_replay_default_mode_completed_with_recorded_provenance():
    response = routes.simulate_compat(req=SimulationRequest(scenario="baseline"))

    assert response.status == "completed"
    assert response.mode == "replay"
    assert response.requested_parameters["mode"] == "replay"
    assert response.result_reference["live_simulation"] is False
    assert response.result_reference["mode_label"] == "recorded_replay"
    assert response.result_reference["provenance"]["fixture_id"] == "phase_bootstrap_normal"
    assert response.result_reference["provenance"]["checksums_verified"] is True
    assert response.result_reference["provenance"]["created_from_existing_repository_artifact"] is True
    assert response.result_reference["provenance"]["parser"].endswith("KPIParser.parse_sca_file")
    assert response.metrics["aggregate"]["throughput_mbps"] == 2.1548


@pytest.mark.parametrize("alias", sorted(REPLAY_SCENARIO_ALIASES))
def test_supported_replay_aliases_map_to_bootstrap_fixture(alias):
    response = routes.simulate_compat(req=SimulationRequest(scenario=alias, mode="replay"))

    assert response.applied_parameters["scenario_fixture_mapping"] == {alias: "phase_bootstrap_normal"}
    assert response.applied_parameters["fixture_id"] == "phase_bootstrap_normal"


@pytest.mark.parametrize("scenario", ["handover_failure", "energy_optimization", "hotspot_traffic_burst"])
def test_unsupported_replay_scenarios_do_not_receive_healthy_fixture(scenario):
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.post("/simulate", json={"scenario": scenario, "mode": "replay"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "unsupported_replay_scenario"


def test_replay_does_not_mark_request_metadata_as_applied():
    response = routes.simulate_compat(
        req=SimulationRequest(
            scenario="baseline",
            ue_count=30,
            cell_id=3,
            slice_type="URLLC",
            seed=7,
            mode="replay",
        )
    )

    assert response.applied_parameters == {
        "mode": "replay",
        "scenario_alias": "baseline",
        "fixture_id": "phase_bootstrap_normal",
        "scenario_fixture_mapping": {"baseline": "phase_bootstrap_normal"},
    }
    for field in ["ue_count", "cell_id", "slice_type", "seed"]:
        assert field in response.unsupported_parameters
    assert response.result_reference["recorded_fixture_parameters"]["ue_count"] == "12"


def test_repeated_replay_calls_produce_equivalent_metrics():
    first = routes.simulate_compat(req=SimulationRequest(scenario="baseline", mode="replay"))
    second = routes.simulate_compat(req=SimulationRequest(scenario="baseline", mode="replay"))

    assert first.run_id != second.run_id
    assert first.run_id.startswith("replay-phase_bootstrap_normal-")
    assert second.run_id.startswith("replay-phase_bootstrap_normal-")
    assert first.metrics == second.metrics


@dataclass
class FakePhase:
    name: str
    returncode: int
    kpis: dict


class RouteFakeRunner:
    def __init__(self, *, running=True, history=None, metrics=None):
        self.running = running
        self.history = history if history is not None else []
        self.started = False
        self.metrics = metrics if metrics is not None else {}

    def start(self):
        self.started = True
        self.running = True

    def snapshot(self):
        return {
            "running": self.running,
            "engine": "simu5g",
            "current_phase": "phase_01_normal",
            "cumulative_sim_time_s": 12.5,
            "gnbs": [{"id": 0}],
            "last_completed_phase_kpis": {"aggregate": self.metrics},
        }


def _client_with_runner(monkeypatch, runner):
    monkeypatch.setattr(routes, "runner", runner)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def _live_available(monkeypatch):
    monkeypatch.setattr(
        routes,
        "build_capabilities",
        lambda settings, replay_service, runner=None: {
            "live_enabled": True,
            "live_available": True,
            "missing_live_requirements": [],
        },
    )


def test_live_disabled_returns_structured_unavailable(monkeypatch):
    client = _client_with_runner(monkeypatch, RouteFakeRunner(running=False))

    response = client.post("/simulate", json={"scenario": "baseline", "mode": "live"})

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "failed"
    assert body["mode"] == "live"
    assert body["error"]["code"] == "live_mode_disabled"
    assert body["result_reference"]["replay_fallback_used"] is False


def test_live_enabled_but_prerequisites_missing_returns_unavailable(monkeypatch):
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "true")
    client = _client_with_runner(monkeypatch, RouteFakeRunner(running=False))

    response = client.post("/simulate", json={"scenario": "baseline", "mode": "live"})

    assert response.status_code == 503
    body = response.json()
    assert body["error"]["code"] == "live_mode_unavailable"
    assert body["result_reference"]["replay_fallback_used"] is False
    assert body["metrics"] == {}


def test_live_runner_start_returns_started_when_available(monkeypatch):
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "true")
    _live_available(monkeypatch)
    fake = RouteFakeRunner(running=False)
    client = _client_with_runner(monkeypatch, fake)

    response = client.post("/simulate", json={"scenario": "baseline", "mode": "live"})

    assert response.status_code == 200
    assert response.json()["status"] == "started"
    assert fake.started is True


def test_live_completion_requires_successful_phase_with_metrics(monkeypatch):
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "true")
    _live_available(monkeypatch)
    phase = FakePhase(
        name="phase_bootstrap_normal",
        returncode=0,
        kpis={"aggregate": {"throughput_mbps": 1.2}},
    )
    client = _client_with_runner(monkeypatch, RouteFakeRunner(running=True, history=[phase]))

    response = client.post("/simulate", json={"scenario": "baseline", "mode": "live"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["metrics"] == {"throughput_mbps": 1.2}
    assert body["result_reference"]["last_completed_phase"] == "phase_bootstrap_normal"


def test_live_runner_failure_remains_failed_without_stale_metrics(monkeypatch):
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "true")
    _live_available(monkeypatch)
    phase = FakePhase(name="phase_failure", returncode=1, kpis={"aggregate": {"throughput_mbps": 99}})
    client = _client_with_runner(
        monkeypatch,
        RouteFakeRunner(running=True, history=[phase], metrics={"throughput_mbps": 12.3}),
    )

    response = client.post("/simulate", json={"scenario": "baseline", "mode": "live"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["metrics"] == {}
    assert body["error"]["code"] == "live_runner_phase_failed"


def test_live_empty_output_does_not_return_completed(monkeypatch):
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "true")
    _live_available(monkeypatch)
    phase = FakePhase(name="phase_empty", returncode=0, kpis={"aggregate": {}})
    client = _client_with_runner(monkeypatch, RouteFakeRunner(running=True, history=[phase]))

    response = client.post("/simulate", json={"scenario": "baseline", "mode": "live"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "live_output_empty"


def test_query_compatibility_uses_same_replay_dispatch():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.post("/simulate?scenario=baseline&ue_count=20&cell_id=cell-1&mode=replay")

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "replay"
    assert body["requested_parameters"]["scenario"] == "baseline"
    assert body["requested_parameters"]["ue_count"] == 20
    assert body["requested_parameters"]["cell_id"] == "cell-1"


def test_json_body_wins_over_query_parameters():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.post(
        "/simulate?scenario=handover_failure&mode=live",
        json={"scenario": "baseline", "ue_count": 7, "cell_id": "cell-9", "mode": "replay"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "replay"
    assert body["requested_parameters"]["scenario"] == "baseline"
    assert body["requested_parameters"]["ue_count"] == 7
    assert "JSON body is used" in body["compatibility"]


@pytest.mark.parametrize(
    "payload",
    [
        {"scenario": "baseline", "ue_count": 0},
        {"scenario": "baseline", "ue_count": 101},
        {"scenario": "baseline", "mode": "batch"},
        {"scenario": "unsupported_scenario"},
    ],
)
def test_simulate_route_rejects_invalid_json(payload):
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.post("/simulate", json=payload)

    assert response.status_code == 422


def test_simulate_route_rejects_malformed_json():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.post(
        "/simulate",
        data="{not-json",
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 422


def test_health_liveness_does_not_claim_live_readiness():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["process_liveness"] is True
    assert "live_available" not in body


def test_ready_reports_replay_and_live_independently():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["default_mode"] == "replay"
    assert body["replay_available"] is True
    assert body["live_enabled"] is False
    assert body["live_available"] is False


def test_ready_503_when_default_live_unavailable(monkeypatch):
    monkeypatch.setenv("SIMULATION_DEFAULT_MODE", "live")
    monkeypatch.setenv("SIMULATION_LIVE_ENABLED", "false")
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["default_mode"] == "live"
    assert body["default_mode_available"] is False


def test_capabilities_contains_no_secret_or_absolute_path_values():
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    response = client.get("/capabilities")

    assert response.status_code == 200
    text = response.text
    assert "SECRET" not in text.upper()
    assert "TOKEN" not in text.upper()
    assert "/opt/" not in text
    assert "C:\\" not in text
