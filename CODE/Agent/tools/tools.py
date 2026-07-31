import json
import os

import requests

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        return False


load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

SIM_SERVICE_URL = ""
RAG_SERVICE_URL = ""


def _base_url_from_env(primary: str, legacy: str, default: str) -> str:
    value = os.environ.get(primary) or os.environ.get(legacy) or default
    value = value.strip().rstrip("/")
    return value or default


def _refresh_service_urls() -> None:
    global SIM_SERVICE_URL, RAG_SERVICE_URL
    SIM_SERVICE_URL = _base_url_from_env(
        "SIMULATION_BASE_URL",
        "SIM_SERVICE_URL",
        "http://localhost:7000",
    )
    RAG_SERVICE_URL = _base_url_from_env(
        "RAG_BASE_URL",
        "RAG_SERVICE_URL",
        "http://localhost:7001",
    )


_refresh_service_urls()

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


def call_simulation(
    scenario: str,
    ue_count: int = 20,
    cell_id: int = 0,
    slice_type: str = "eMBB",
) -> str:
    """Call the canonical Simulation REST endpoint and return structured JSON text."""
    _refresh_service_urls()
    mapped_scenario = SCENARIO_ALIASES.get(scenario, scenario)
    payload = {
        "scenario": mapped_scenario,
        "ue_count": ue_count,
        "cell_id": cell_id,
        "slice_type": slice_type,
        "mode": "live",
    }

    try:
        resp = requests.post(
            f"{SIM_SERVICE_URL}/simulate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, dict):
            raise ValueError("Simulation response JSON was not an object.")

        normalized = {
            "status": raw.get("status", "unknown"),
            "run_id": raw.get("run_id"),
            "mode": raw.get("mode"),
            "requested_scenario": scenario,
            "scenario": mapped_scenario,
            "ue_count": ue_count,
            "cell_id": cell_id,
            "slice_type": slice_type,
            "requested_parameters": raw.get("requested_parameters", {}),
            "applied_parameters": raw.get("applied_parameters", {}),
            "unsupported_parameters": raw.get("unsupported_parameters", {}),
            "metrics": raw.get("metrics", {}),
            "result_reference": raw.get("result_reference", {}),
            "error": raw.get("error"),
            "raw": raw,
        }
        return json.dumps(normalized)

    except requests.exceptions.ConnectionError:
        return json.dumps(
            {
                "error": "Simulation service is unreachable.",
                "hint": f"Check whether the Simulation service is reachable at {SIM_SERVICE_URL}.",
            }
        )
    except requests.exceptions.Timeout:
        return json.dumps(
            {
                "error": "Simulation timed out after 120 seconds.",
                "hint": "Try a smaller ue_count or check whether the simulation backend is hanging.",
            }
        )
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "unknown"
        detail = e.response.text if e.response is not None else str(e)
        return json.dumps(
            {
                "error": f"Simulation service returned HTTP {status}",
                "detail": detail,
            }
        )
    except ValueError as e:
        return json.dumps(
            {
                "error": "Simulation service returned malformed JSON.",
                "detail": str(e),
            }
        )
    except Exception as e:
        return json.dumps(
            {
                "error": "Unexpected simulation tool failure.",
                "detail": str(e),
            }
        )


def call_rag(query: str) -> str:
    """Call the canonical structured RAG retrieval endpoint."""
    _refresh_service_urls()
    try:
        resp = requests.post(
            f"{RAG_SERVICE_URL}/v1/retrievaltool/json",
            json={"text": query},
            timeout=30,
        )
        resp.raise_for_status()
        raw = resp.json()
        if not isinstance(raw, dict):
            raise ValueError("RAG response JSON was not an object.")
        return json.dumps(raw)

    except requests.exceptions.ConnectionError:
        return json.dumps(
            {
                "error": "RAG service is unreachable.",
                "hint": f"Is the RAG retrieval service running at {RAG_SERVICE_URL}?",
            }
        )
    except requests.exceptions.Timeout:
        return json.dumps({"error": "RAG service timed out after 30 seconds."})
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "unknown"
        detail = e.response.text if e.response is not None else str(e)
        return json.dumps(
            {
                "error": f"RAG service returned HTTP {status}",
                "detail": detail,
            }
        )
    except ValueError as e:
        return json.dumps(
            {
                "error": "RAG service returned malformed JSON.",
                "detail": str(e),
            }
        )


def call_simulation_stub(scenario: str, ue_count: int = 20, cell_id: int = 0) -> str:
    """Local-only deterministic stub for manual tool development."""
    return json.dumps(
        {
            "throughput_mbps": 45.2,
            "latency_ms": 12.8,
            "sinr_db": 8.4,
            "packet_loss_pct": 1.2,
            "handover_count": 5,
            "scenario": scenario,
            "ue_count": ue_count,
            "cell_id": cell_id,
            "simulation_time_s": 2.1,
        }
    )


def call_rag_stub(query: str) -> str:
    """Local-only deterministic stub for manual tool development."""
    return (
        "[O-RAN.WG2.Non-RT-RIC-ARCH-R003, Section 5.2] "
        "Throughput degradation in 5G NR is commonly caused by co-channel "
        "interference, PDSCH scheduling bottlenecks, or excessive handovers. "
        "Recommended remediation: adjust antenna tilt, reduce TX power, "
        "or update the Near-RT RIC A1 policy for load balancing."
    )
