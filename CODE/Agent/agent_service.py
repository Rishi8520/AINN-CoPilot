import asyncio
from contextlib import asynccontextmanager
import os
import re
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

from common.jobs import JobConflict, JobQueue, QueueFull, TERMINAL

from agent import IntentType, classify_intent


def _base_url_from_env(primary: str, legacy: str, default: str) -> str:
    value = os.getenv(primary) or os.getenv(legacy) or default
    value = value.strip().rstrip("/")
    return value or default


SIMULATION_BASE_URL = _base_url_from_env("SIMULATION_BASE_URL", "SIM_SERVICE_URL", "http://simulation:7000")
RAG_BASE_URL = _base_url_from_env("RAG_BASE_URL", "RAG_SERVICE_URL", "http://rag:7001")
AGENT_PORT = int(os.getenv("AGENT_PORT", "9090"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "60"))
SIMULATION_MODE = os.getenv("AGENT_SIMULATION_MODE", "replay")


@asynccontextmanager
async def lifespan(app):
    await jobs.start()
    yield
    await jobs.stop()

app = FastAPI(
    title="TelcoMind Agent",
    description="Simulation jobs, standards retrieval and evidence-grounded synthesis.",
    version="1.0.0",
    lifespan=lifespan,
)


class SimulationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["live", "replay"] | None = None
    scenario: str | None = Field(None, max_length=80)
    ue_count: int | None = Field(None, ge=1, le=200, strict=True)
    duration: float = Field(10, ge=3, le=120, allow_inf_nan=False)
    seed: int = Field(42, ge=0, le=2147483647, strict=True)
    bands: int = Field(50, ge=5, le=100, strict=True)
    comparison_bands: int = Field(10, ge=5, le=100, strict=True)
    burst_multiplier: float = Field(4, ge=2, le=10, allow_inf_nan=False)
    speed_mps: float = Field(60, ge=1, le=100, allow_inf_nan=False)


class ChatCompletionRequest(BaseModel):
    messages: Any
    thread_id: str | None = None
    stream: bool = False
    request_id: str | None = Field(None, max_length=128)
    simulation: SimulationOptions | None = None


def _message_text(messages: Any) -> str:
    if isinstance(messages, str):
        return messages.strip()
    if isinstance(messages, list):
        parts: list[str] = []
        for item in messages:
            if isinstance(item, dict):
                content = item.get("content")
                if isinstance(content, str):
                    parts.append(content)
        return "\n".join(parts).strip()
    return str(messages or "").strip()


def _select_simulation_request(query: str, options: SimulationOptions | None = None) -> dict[str, Any]:
    lowered = query.lower()
    scenario = "baseline"
    # Only use non-baseline scenarios when the caller explicitly asks to simulate them.
    if _needs_simulation(query):
        if "handover_failure" in lowered or "handover stress" in lowered or "handover failure" in lowered:
            scenario = "handover_failure"
        elif "energy_optimization" in lowered or "energy optimization" in lowered or "energy saving" in lowered:
            scenario = "energy_optimization"
        elif "interference" in lowered:
            scenario = "interference_hotspot"
        elif any(word in lowered for word in ("resource comparison", "resource_comparison", "compare resources", "compare bandwidth", "compare bands")):
            scenario = "resource_comparison"
        elif any(word in lowered for word in ("traffic burst", "traffic_burst", "hotspot_traffic_burst")):
            scenario = "traffic_burst"
        elif any(word in lowered for word in ("mobility", "handover", "moving ue")):
            scenario = "mobility_handover"
    options = options or SimulationOptions()
    match = re.search(r"\b(\d+)\s*(?:ues?|users?)\b", lowered)
    count = options.ue_count if options.ue_count is not None else int(match.group(1)) if match else 10
    if not 1 <= count <= 200:
        raise HTTPException(422, "UE count must be between 1 and 200")
    return {
        "scenario": options.scenario or scenario,
        "ue_count": count,
        "cell_id": "cell-1",
        "slice_type": "eMBB",
        "mode": options.mode or ("replay" if "replay" in lowered else SIMULATION_MODE),
        "seed": options.seed,
        "duration": options.duration,
        **{key: getattr(options, key) for key in ("bands", "comparison_bands", "burst_multiplier", "speed_mps")},
    }


def _needs_simulation(query):
    text = query.lower()
    explicit = re.search(r"\b(simulate|simulation|replay|diagnose|diagnosis|investigate|run|measure|compare)\b", text)
    if explicit:
        return True
    if any(word in text for word in ("according to", "3gpp", "standard", "what is", "what causes", "explain")):
        return False
    return classify_intent(query) in {IntentType.SIMULATION, IntentType.HYBRID}


async def _get_json(client: httpx.AsyncClient, base_url: str, path: str) -> dict[str, Any]:
    response = await client.get(f"{base_url}{path}")
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError(f"{base_url}{path} returned non-object JSON")
    return body


async def _post_json(client: httpx.AsyncClient, base_url: str, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = await client.post(f"{base_url}{path}", json=payload)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError(f"{base_url}{path} returned non-object JSON")
    return body


@app.get("/v1/health_check")
async def health_check(response: Response):
    timeout = httpx.Timeout(5.0)
    checks: dict[str, Any] = {}
    ready = True
    async with httpx.AsyncClient(timeout=timeout) as client:
        for name, base_url in {"simulation": SIMULATION_BASE_URL, "rag": RAG_BASE_URL}.items():
            started = time.monotonic()
            try:
                body = await _get_json(client, base_url, "/ready")
                reachable = True
                status = "ready" if body.get("ready", True) is not False else "not_ready"
            except Exception as exc:
                reachable = False
                status = "unreachable"
                body = {"error": str(exc)}
                ready = False
            checks[name] = {
                "url": base_url,
                "reachable": reachable,
                "status": status,
                "latency_ms": round((time.monotonic() - started) * 1000, 1),
                "details": body,
            }
            if not reachable or status != "ready":
                ready = False
    if not ready:
        response.status_code = 503
    return {
        "status": "healthy" if ready else "degraded",
        "ready": ready,
        "agent_profile": "live" if SIMULATION_MODE == "live" else "quickstart",
        "simulation_mode": SIMULATION_MODE,
        "synthesis_backend": checks.get("rag", {}).get("details", {}).get("synthesis", {}).get("requested_backend", "deterministic"),
        "llm_used": False,
        "services": checks,
    }


@app.get("/v1/tools")
async def tools():
    return {
        "tools": [
            {
                "name": "simulation",
                "base_url": SIMULATION_BASE_URL,
                "mode": SIMULATION_MODE,
                "endpoint": "/jobs" if SIMULATION_MODE == "live" else "/simulate",
            },
            {
                "name": "rag_quickstart",
                "base_url": RAG_BASE_URL,
                "profile": "quickstart",
                "retrieval_endpoint": "/v1/retrievaltool/json",
                "synthesis_endpoint": "/synthesize",
            },
        ]
    }


async def _simulate_live(client, payload, request_id, update, cancellation):
    payload = {key: payload[key] for key in ("scenario", "mode", "ue_count", "duration", "seed", "bands", "comparison_bands", "burst_multiplier", "speed_mps")}
    payload["request_id"] = request_id
    job = await _post_json(client, SIMULATION_BASE_URL, "/jobs", payload)
    simulation_id = job["job_id"]
    update(simulation_job_id=simulation_id)
    deadline = time.monotonic() + float(os.getenv("AGENT_JOB_TIMEOUT_SECONDS", "420"))
    try:
        while job["status"] not in TERMINAL:
            if cancellation is not None and cancellation.is_set():
                raise RuntimeError("Query cancelled")
            if time.monotonic() > deadline:
                raise RuntimeError("Simulation job exceeded the Agent deadline")
            update(stage=job.get("stage", "simulating"), progress=0.1 + job.get("progress", 0) * 0.6,
                   simulated_seconds=job.get("simulated_seconds", 0), timeline=job.get("timeline", []))
            await asyncio.sleep(0.5)
            job = await _get_json(client, SIMULATION_BASE_URL, f"/jobs/{simulation_id}")
        if job["status"] != "completed":
            raise RuntimeError(job.get("error") or f"Simulation {job['status']}")
        return job["result"]
    finally:
        if job["status"] not in TERMINAL:
            try:
                await client.delete(f"{SIMULATION_BASE_URL}/jobs/{simulation_id}")
            except httpx.RequestError:
                pass


def _synthesis_context(simulation):
    context = {key: simulation.get(key) for key in ("mode", "scenario", "ue_count", "duration_seconds", "seed")}
    context["mobility"] = simulation.get("topology", {}).get("mobility")
    context["measurement"] = simulation.get("measurement", {})
    context["parameters"] = simulation.get("parameters", {})
    context["phases"] = simulation.get("phases", [])
    context["handover"] = {key: simulation.get("handover", {}).get(key) for key in ("serving_cell_transitions", "detachments", "measured_ues", "note")}
    if simulation.get("comparison"):
        comparison = simulation["comparison"]
        context["comparison"] = {key: comparison[key] for key in ("reference_bands", "candidate_bands", "delta_candidate_minus_reference", "note")}
        context["comparison"]["candidate_metrics"] = comparison["candidate"]["metrics"]
        context["comparison"]["reference_metrics"] = comparison["reference"]["metrics"]
    rows = simulation.get("per_ue", [])
    context["per_ue_summary"] = {}
    for metric in ("throughput_mbps", "latency_ms", "undelivered_percent"):
        values = [row[metric] for row in rows if isinstance(row.get(metric), (int, float))]
        if values:
            context["per_ue_summary"][metric] = {"min": min(values), "max": max(values), "count": len(values)}
    return context


async def _execute_query(req: ChatCompletionRequest, update=lambda **fields: None, cancellation=None):
    query = _message_text(req.messages)
    if not query:
        raise HTTPException(status_code=400, detail="messages/query content is required")

    intent = classify_intent(query)
    request_id = req.request_id or f"agent-{uuid.uuid4()}"
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    simulation = {}
    simulated = _needs_simulation(query)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            if simulated:
                selected = _select_simulation_request(query, req.simulation)
                update(stage="simulating", progress=0.1)
                if selected["mode"] == "live":
                    simulation = await _simulate_live(client, selected, request_id, update, cancellation)
                else:
                    selected.pop("duration")
                    for key in ("bands", "comparison_bands", "burst_multiplier", "speed_mps"):
                        selected.pop(key)
                    simulation = await _post_json(client, SIMULATION_BASE_URL, "/simulate", selected)
                update(simulation=simulation)
            if cancellation is not None and cancellation.is_set():
                raise RuntimeError("Query cancelled")
            update(stage="retrieving", progress=0.75)
            retrieval = await _post_json(
                client,
                RAG_BASE_URL,
                "/v1/retrievaltool/json",
                {
                    "text": query,
                    "top_k": 4,
                },
            )
            update(stage="synthesizing", progress=0.9)
            synthesis = await _post_json(
                client,
                RAG_BASE_URL,
                "/synthesize",
                {
                    "query": query,
                    "top_k": 4,
                    "contexts": retrieval.get("sources", []),
                    "simulation_kpis": simulation.get("metrics", {}).get("aggregate", simulation.get("metrics", {})) or None,
                    "simulation_context": _synthesis_context(simulation) if simulated else None,
                    "intent_type": "DIAGNOSTIC" if simulated else "GENERAL_QNA",
                },
            )
        except httpx.HTTPStatusError as exc:
            detail = {
                "message": "A downstream quickstart service returned an error.",
                "service_url": str(exc.request.url),
                "status_code": exc.response.status_code,
                "body": exc.response.text[:1000],
            }
            raise HTTPException(status_code=502, detail=detail) from exc
        except (httpx.RequestError, ValueError) as exc:
            detail = {
                "message": "A downstream quickstart service could not be reached or returned malformed data.",
                "error": str(exc),
            }
            raise HTTPException(status_code=502, detail=detail) from exc

    status = "completed" if (not simulated or simulation.get("status") == "completed") and retrieval.get("result_count", 0) > 0 else "degraded"
    return {
        "id": f"telcomind-quickstart-{req.thread_id or 'thread'}",
        "request_id": request_id,
        "object": "chat.completion",
        "agent_profile": "live" if SIMULATION_MODE == "live" else "quickstart",
        "status": status,
        "intent": intent.value,
        "thread_id": req.thread_id,
        "response": synthesis.get("answer", ""),
        "simulation": simulation,
        "rag": retrieval,
        "synthesis": synthesis,
        "evidence": {
            "simulation_reached": simulated,
            "rag_reached": True,
            "request_id": request_id,
            "simulation_mode": simulation.get("mode"),
            "rag_profile": retrieval.get("rag_profile"),
            "retrieval_backend": retrieval.get("retrieval_backend"),
            "synthesis_backend": synthesis.get("synthesis_backend"),
            "llm_used": synthesis.get("llm_used"),
        },
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": synthesis.get("answer", ""),
                },
                "finish_reason": status,
            }
        ],
    }


async def execute_job(record, cancellation):
    request = ChatCompletionRequest(**record["request"])
    request.request_id = record["job_id"]
    return await _execute_query(request, lambda **fields: jobs.update(record["job_id"], **fields), cancellation)


jobs = JobQueue(os.getenv("AGENT_JOB_DIRECTORY", "/tmp/agent-jobs"), execute_job, capacity=8)


@app.post("/v1/jobs", status_code=202)
async def submit_job(req: ChatCompletionRequest):
    query = _message_text(req.messages)
    if not query:
        raise HTTPException(400, "messages/query content is required")
    if _needs_simulation(query):
        selected = _select_simulation_request(query, req.simulation)
        if selected["mode"] == "live" and selected["scenario"] not in {"baseline", "normal_operation", "traffic_burst", "resource_comparison", "mobility_handover"}:
            raise HTTPException(422, "Unsupported live scenario. Supported: baseline, traffic_burst, resource_comparison, mobility_handover. Fault injection is not implemented.")
        if selected["scenario"] == "resource_comparison" and selected["bands"] == selected["comparison_bands"]:
            raise HTTPException(422, "Choose two different resource band counts")
    try:
        return jobs.submit(req.model_dump(exclude={"request_id"}), req.request_id)
    except JobConflict as error:
        raise HTTPException(409, str(error)) from error
    except QueueFull as error:
        raise HTTPException(429, str(error), headers={"Retry-After": "5"}) from error


@app.get("/v1/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, "Unknown query job")


@app.delete("/v1/jobs/{job_id}")
async def cancel_job(job_id: str):
    await get_job(job_id)
    return jobs.cancel(job_id)


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    return await _execute_query(req)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
