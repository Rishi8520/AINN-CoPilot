import os
import json
import requests
from dotenv import load_dotenv

# Load from CODE/.env (two levels up from this file)
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

SIM_SERVICE_URL = os.environ.get("SIM_SERVICE_URL", "http://localhost:8888")
RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://localhost:8889")


def call_simulation(scenario: str, ue_count: int = 20, cell_id: int = 0) -> str:
    """
    Calls Member 1's Simu5G REST endpoint.

    Valid scenarios:
        baseline, high_load, interference_high, handover_stress, energy_saving

    Returns a JSON string with KPIs:
        throughput_mbps, latency_ms, sinr_db, packet_loss_pct,
        handover_count, simulation_time_s
    """
    payload = {
        "scenario": scenario,
        "ue_count": ue_count,
        "cell_id": cell_id
    }
    try:
        resp = requests.post(
            f"{SIM_SERVICE_URL}/simulate",
            json=payload,
            timeout=120   # simulations can take up to 2 minutes
        )
        resp.raise_for_status()
        return json.dumps(resp.json())

    except requests.exceptions.ConnectionError:
        return json.dumps({
            "error": "Simulation service is unreachable.",
            "hint": f"Is Member 1's container running at {SIM_SERVICE_URL}?"
        })
    except requests.exceptions.Timeout:
        return json.dumps({
            "error": "Simulation timed out after 120 seconds.",
            "hint": "Try a smaller ue_count or check if OMNeT++ is hanging."
        })
    except requests.exceptions.HTTPError as e:
        return json.dumps({
            "error": f"Simulation service returned HTTP {resp.status_code}",
            "detail": str(e)
        })


def call_rag(query: str) -> str:
    """
    Calls Member 2's RAG retrieval endpoint.

    Queries the 3GPP / O-RAN knowledge base and returns
    reranked relevant text chunks with source references.
    """
    payload = {"text": query}
    try:
        resp = requests.post(
            f"{RAG_SERVICE_URL}/v1/retrievaltool",
            json=payload,
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
            "error": f"RAG service returned HTTP {resp.status_code}",
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