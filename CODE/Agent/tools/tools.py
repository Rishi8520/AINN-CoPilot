import os
import json
import requests
from dotenv import load_dotenv

# load_dotenv is only effective locally; inside Docker, env vars are
# injected by docker-compose via the 'environment:' block in docker-compose.yml
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

SIM_SERVICE_URL = os.environ.get("SIM_SERVICE_URL", "http://localhost:8888")
RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://localhost:8889")
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
    """
    Calls Member 1's Simu5G REST endpoint over Tailscale.

    Accepts friendly scenario aliases used by the Agent and maps them to
    Member 1's current Simulation scenario names.
    """
    mapped_scenario = SCENARIO_ALIASES.get(scenario, scenario)

    payload = {
        "scenario": mapped_scenario,
        "ue_count": ue_count,
        "cell_id": cell_id,
        "slice_type": slice_type,
    }

    try:
        resp = requests.post(
            f"{SIM_SERVICE_URL}/simulate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        raw = resp.json()

        data = raw.get("data", raw)
        metrics = data.get("metrics", raw.get("metrics", {}))

        normalized = {
            "status": raw.get("status", "success"),
            "requested_scenario": scenario,
            "scenario": mapped_scenario,
            "ue_count": ue_count,
            "cell_id": cell_id,
            "slice_type": slice_type,
            "metrics": metrics,
            "topology": data.get("cluster_topology"),
            "sector_prb_matrix": data.get("sector_prb_matrix"),
            "raw": raw,
        }

        return json.dumps(normalized)

    except requests.exceptions.ConnectionError:
        return json.dumps({
            "error": "Simulation service is unreachable.",
            "hint": f"Check whether Member 1's Simulation service is reachable at {SIM_SERVICE_URL} over Tailscale.",
        })
    except requests.exceptions.Timeout:
        return json.dumps({
            "error": "Simulation timed out after 120 seconds.",
            "hint": "Try a smaller ue_count or check whether the simulation backend is hanging.",
        })
    except requests.exceptions.HTTPError as e:
        return json.dumps({
            "error": f"Simulation service returned HTTP {e.response.status_code if e.response else 'unknown'}",
            "detail": str(e),
        })
    except Exception as e:
        return json.dumps({
            "error": "Unexpected simulation tool failure.",
            "detail": str(e),
        })


def call_rag(query: str) -> str:
    """
    Calls Member 2's RAG retrieval endpoint.

    Queries the 3GPP / O-RAN knowledge base and returns
    reranked relevant text chunks with source references.
    """
    # OPEA retrievaltool expects a JSON string sent as raw data,
    # NOT a dict via json= kwarg — must use data= with explicit header.
    content = json.dumps({"text": query})
    try:
        resp = requests.post(
            f"{RAG_SERVICE_URL}/v1/retrievaltool",
            data=content,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        resp.raise_for_status()
        return resp.text

    except requests.exceptions.ConnectionError:
        return json.dumps({
            "error": "RAG service is unreachable.",
            "hint": f"Is Member 2's retrieval container running at {RAG_SERVICE_URL}?"
        })
    except requests.exceptions.Timeout:
        return json.dumps({
            "error": "RAG service timed out after 30 seconds."
        })
    except requests.exceptions.HTTPError as e:
        return json.dumps({
            "error": f"RAG service returned HTTP {e.response.status_code if e.response else 'unknown'}",
            "detail": str(e)
        })


# ── Stub mode for local testing without real services ─────────────
# When both services are down, you can test the agent's reasoning
# by temporarily replacing the functions above with these stubs.

def call_simulation_stub(scenario: str, ue_count: int = 20, cell_id: int = 0) -> str:
    """Hardcoded stub — use when Member 1's service is not yet ready."""
    return json.dumps({
        "throughput_mbps": 45.2,
        "latency_ms": 12.8,
        "sinr_db": 8.4,
        "packet_loss_pct": 1.2,
        "handover_count": 5,
        "scenario": scenario,
        "simulation_time_s": 2.1
    })


def call_rag_stub(query: str) -> str:
    """Hardcoded stub — use when Member 2's service is not yet ready."""
    return (
        "[O-RAN.WG2.Non-RT-RIC-ARCH-R003, Section 5.2] "
        "Throughput degradation in 5G NR is commonly caused by co-channel "
        "interference, PDSCH scheduling bottlenecks, or excessive handovers. "
        "Recommended remediation: adjust antenna tilt, reduce TX power, "
        "or update the Near-RT RIC A1 policy for load balancing."
    )