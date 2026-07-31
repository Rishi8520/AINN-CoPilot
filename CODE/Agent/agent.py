# CODE/Agent/agent.py
# AINN-CoPilot — Agent Bootstrap & Orchestration Layer
# Member 3 owns this file.
#
# PURPOSE:
#   This module does NOT replace opea/agent. Instead it:
#   1. Validates that all required tools are reachable before the agent starts
#   2. Provides a local AgentRunner class for unit-testing tool chains without Docker
#   3. Exposes a /v1/agent/status endpoint (imported by gateway.py) for observability
#   4. Houses the intent classification helper used by gateway.py to short-circuit
#      simple queries (skipping the full LLM round-trip when unnecessary)

import os
import json
import httpx
import asyncio
import logging
import re
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ainn.agent")

# ── Endpoints (injected via docker-compose environment) ───────────────────────
def _base_url_from_env(primary: str, legacy: str | list[str], default: str) -> str:
    legacy_names = [legacy] if isinstance(legacy, str) else legacy
    value = os.getenv(primary) or next((os.getenv(name) for name in legacy_names if os.getenv(name)), None) or default
    value = value.strip().rstrip("/")
    return value or default


AGENT_ENDPOINT = _base_url_from_env("AGENT_BASE_URL", "AGENT_ENDPOINT", "http://agent:9090")
SIM_SERVICE_URL = _base_url_from_env("SIMULATION_BASE_URL", "SIM_SERVICE_URL", "http://simulation:7000")
RAG_SERVICE_URL = _base_url_from_env("RAG_BASE_URL", "RAG_SERVICE_URL", "http://rag:7001")

SIM_HEALTH_PATH = os.getenv("SIM_HEALTH_PATH", "/health")
RAG_HEALTH_PATH = os.getenv("RAG_HEALTH_PATH", "/health")
AGENT_HEALTH_PATH = os.getenv("AGENT_HEALTH_PATH", "/v1/health_check")
LLM_ENDPOINT = _base_url_from_env("LLM_BASE_URL", ["VLLM_BASE_URL", "LLM_ENDPOINT_URL"], "")
HEALTH_PROBE_TIMEOUT_SECONDS = float(os.getenv("HEALTH_PROBE_TIMEOUT_SECONDS", "4.0"))
STARTUP_PROBE_RETRIES = int(os.getenv("STARTUP_PROBE_RETRIES", "5"))
STARTUP_PROBE_DELAY_SECONDS = float(os.getenv("STARTUP_PROBE_DELAY_SECONDS", "6.0"))

# ── Intent types — keeps gateway routing explicit ─────────────────────────────
class IntentType(str, Enum):
    SIMULATION   = "simulation"    # needs live Simu5G KPIs
    RAG_ONLY     = "rag_only"      # pure 3GPP/O-RAN knowledge lookup
    HYBRID       = "hybrid"        # needs both tools
    HEALTH_CHECK = "health_check"  # system status query
    UNKNOWN      = "unknown"       # let the LLM agent decide

# ── Tool health status model ──────────────────────────────────────────────────
class ToolStatus(BaseModel):
    name: str
    url: str
    reachable: bool
    latency_ms: Optional[float] = None
    error: Optional[str] = None

class AgentStatus(BaseModel):
    opea_agent_ready: bool
    tools: list[ToolStatus]
    intent_classifier_ready: bool = True

# ── Keyword maps for lightweight intent classification ─────────────────────────
# These run BEFORE the LLM to short-circuit obvious queries.
# If none match → IntentType.UNKNOWN → full LLM ReAct loop decides.
_SIM_KEYWORDS = [
    "sinr", "throughput", "latency", "packet loss", "handover",
    "simulate", "simulation", "ran", "gnb", "ue", "bearer",
    "signal", "kpi", "channel", "interference", "coverage",
    "5g", "nr", "lte", "cell", "sector", "enb", "antenna",
    "beamforming", "prb", "resource block", "modulation",
]
_RAG_KEYWORDS = [
    "standard", "3gpp", "spec", "specification", "ts ", "tr ",
    "o-ran", "oran", "wg", "release", "architecture", "protocol",
    "what is", "define", "definition", "explain", "how does",
    "sla", "qos", "slice", "nsa", "sa ", "standalone", "non-standalone",
    "amf", "smf", "upf", "pcf", "nssf", "ausf", "udm",
]

def classify_intent(query: str) -> IntentType:
    """
    Lightweight keyword-based intent classifier.
    Runs in <1ms — no LLM call needed for obvious queries.
    Returns IntentType so gateway.py can decide routing strategy.
    """
    q = query.lower()
    tokens = set(re.findall(r"[a-z0-9_+-]+", q))

    if any(k in tokens for k in ["health", "status", "ping", "alive", "ready"]):
        return IntentType.HEALTH_CHECK

    has_sim = any(k in q for k in _SIM_KEYWORDS)
    has_rag = any(k in q for k in _RAG_KEYWORDS)

    if has_sim and has_rag:
        return IntentType.HYBRID
    if has_sim:
        return IntentType.SIMULATION
    if has_rag:
        return IntentType.RAG_ONLY

    return IntentType.UNKNOWN  # LLM ReAct loop takes over

# ── Tool reachability probe ───────────────────────────────────────────────────
async def _probe(name: str, url: str, path: str = "/health") -> ToolStatus:
    """
    Pings a tool's health endpoint and measures round-trip latency.
    Called at startup and by /v1/agent/status.
    """
    import time
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=HEALTH_PROBE_TIMEOUT_SECONDS) as client:
            r = await client.get(f"{url}{path}")
            latency = (time.monotonic() - start) * 1000
            return ToolStatus(
                name=name,
                url=url,
                reachable=(r.status_code < 500),
                latency_ms=round(latency, 1),
            )
    except Exception as e:
        latency = (time.monotonic() - start) * 1000
        return ToolStatus(
            name=name,
            url=url,
            reachable=False,
            latency_ms=round(latency, 1),
            error=str(e),
        )

async def get_agent_status() -> AgentStatus:
    """
    Checks opea/agent + both tool backends in parallel.
    Used by gateway.py's /v1/agent/status endpoint.
    """
    results = await asyncio.gather(
        _probe("opea-agent", AGENT_ENDPOINT, AGENT_HEALTH_PATH),
        _probe("simulation", SIM_SERVICE_URL, SIM_HEALTH_PATH),
        _probe("rag-retrieval", RAG_SERVICE_URL, RAG_HEALTH_PATH),
    )
    opea_ok       = results[0].reachable
    tool_statuses = list(results[1:])  # sim + rag

    for ts in tool_statuses:
        emoji = "✅" if ts.reachable else "❌"
        log.info(f"{emoji} {ts.name} @ {ts.url} — {ts.latency_ms}ms")

    return AgentStatus(
        opea_agent_ready=opea_ok,
        tools=tool_statuses,
    )

# ── Startup validator — called by gateway.py on container boot ─────────────────
async def validate_on_startup(
    retry: int = STARTUP_PROBE_RETRIES,
    delay: float = STARTUP_PROBE_DELAY_SECONDS,
):
    """
    Retries tool health probes at startup.
    Logs warnings but does NOT crash the gateway if a tool is down —
    the agent will handle tool errors gracefully at query time.
    """
    log.info("🔍 AINN-CoPilot startup: probing tool backends...")
    for attempt in range(1, retry + 1):
        status = await get_agent_status()
        all_ok = status.opea_agent_ready and all(t.reachable for t in status.tools)

        if all_ok:
            log.info("✅ All systems ready. AINN-CoPilot agent is operational.")
            return status

        down = [t.name for t in status.tools if not t.reachable]
        if not status.opea_agent_ready:
            down.append("opea-agent")

        log.warning(
            f"⏳ Attempt {attempt}/{retry} — waiting for: {down}. "
            f"Retrying in {delay}s..."
        )
        await asyncio.sleep(delay)

    log.warning(
        "⚠️  Some backends unreachable after startup probes. "
        "Gateway will start anyway — queries may partially fail."
    )
    return await get_agent_status()

# ── Local AgentRunner — for unit tests WITHOUT Docker ────────────────────────
class AgentRunner:
    """
    Thin wrapper around the opea/agent HTTP API.
    Use this in tests/test_agent.py to fire queries
    against a live or mocked agent endpoint.

    Example:
        runner = AgentRunner()
        response = await runner.query("What is the SINR at gNB-3?")
    """

    def __init__(self, endpoint: str = AGENT_ENDPOINT):
        self.endpoint = endpoint

    async def query(
        self,
        text: str,
        thread_id: Optional[str] = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "messages": text,
            "thread_id": thread_id or "test-thread",
            "stream": stream,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{self.endpoint}/v1/chat/completions",
                json=payload,
            )
            r.raise_for_status()
            return r.json()

    async def get_tools(self) -> list[dict]:
        """Returns the tool list the agent has loaded — useful for verifying
        that ainn_tools.yaml was mounted and parsed correctly."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.endpoint}/v1/tools")
            r.raise_for_status()
            return r.json()
