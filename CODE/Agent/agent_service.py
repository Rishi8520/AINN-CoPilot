import os
import time
import uuid
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from agent import IntentType, classify_intent


def _base_url_from_env(primary: str, legacy: str, default: str) -> str:
    value = os.getenv(primary) or os.getenv(legacy) or default
    value = value.strip().rstrip("/")
    return value or default


SIMULATION_BASE_URL = _base_url_from_env("SIMULATION_BASE_URL", "SIM_SERVICE_URL", "http://simulation:7000")
RAG_BASE_URL = _base_url_from_env("RAG_BASE_URL", "RAG_SERVICE_URL", "http://rag:7001")
AGENT_PORT = int(os.getenv("AGENT_PORT", "9090"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "60"))

app = FastAPI(
    title="TelcoMind Quickstart Agent",
    description="CPU-safe quickstart orchestration service for Simulation replay and RAG synthesis.",
    version="1.0.0",
)


class ChatCompletionRequest(BaseModel):
    messages: Any
    thread_id: str | None = None
    stream: bool = False
    request_id: str | None = None


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


def _select_simulation_request(query: str) -> dict[str, Any]:
    lowered = query.lower()
    scenario = "baseline"
    # Only use non-baseline scenarios when the caller explicitly asks to simulate them.
    if "simulate" in lowered or "replay" in lowered or "scenario" in lowered:
        if "handover_failure" in lowered or "handover stress" in lowered:
            scenario = "handover_failure"
        elif "energy_optimization" in lowered or "energy optimization" in lowered:
            scenario = "energy_optimization"
        elif "high_load" in lowered or "interference_high" in lowered or "hotspot_traffic_burst" in lowered:
            scenario = "hotspot_traffic_burst"
    return {
        "scenario": scenario,
        "ue_count": 20,
        "cell_id": "cell-1",
        "slice_type": "eMBB",
        "mode": "replay",
    }


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
        "agent_profile": "quickstart",
        "synthesis_backend": "deterministic",
        "llm_used": False,
        "services": checks,
    }


@app.get("/v1/tools")
async def tools():
    return {
        "tools": [
            {
                "name": "simulation_replay",
                "base_url": SIMULATION_BASE_URL,
                "mode": "replay",
                "endpoint": "/simulate",
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


@app.post("/v1/chat/completions")
async def chat_completions(req: ChatCompletionRequest):
    query = _message_text(req.messages)
    if not query:
        raise HTTPException(status_code=400, detail="messages/query content is required")

    intent = classify_intent(query)
    request_id = req.request_id or f"agent-{uuid.uuid4()}"
    timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            simulation = await _post_json(
                client,
                SIMULATION_BASE_URL,
                "/simulate",
                _select_simulation_request(query),
            )
            retrieval = await _post_json(
                client,
                RAG_BASE_URL,
                "/v1/retrievaltool/json",
                {
                    "text": query,
                    "top_k": 4,
                },
            )
            synthesis = await _post_json(
                client,
                RAG_BASE_URL,
                "/synthesize",
                {
                    "query": query,
                    "top_k": 4,
                    "contexts": retrieval.get("sources", []),
                    "simulation_kpis": simulation.get("metrics", {}).get("aggregate", simulation.get("metrics", {})),
                    "intent_type": "DIAGNOSTIC" if intent in {IntentType.SIMULATION, IntentType.HYBRID} else intent.value,
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

    status = "completed" if simulation.get("status") == "completed" and retrieval.get("result_count", 0) > 0 else "degraded"
    return {
        "id": f"telcomind-quickstart-{req.thread_id or 'thread'}",
        "request_id": request_id,
        "object": "chat.completion",
        "agent_profile": "quickstart",
        "status": status,
        "intent": intent.value,
        "thread_id": req.thread_id,
        "response": synthesis.get("answer", ""),
        "simulation": simulation,
        "rag": retrieval,
        "synthesis": synthesis,
        "evidence": {
            "simulation_reached": True,
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=AGENT_PORT)
