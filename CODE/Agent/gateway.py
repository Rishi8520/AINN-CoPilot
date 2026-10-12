# CODE/Agent/gateway.py
# AINN-CoPilot MegaService Gateway
# Member 3 owns this file.
# Sits at :8888 inside Docker, proxies to opea/agent at :9090

import os
import json
import uuid
#import asyncio
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from agent import (
    classify_intent,
    IntentType,
    get_agent_status,
    validate_on_startup,
)
from fastapi.middleware.cors import CORSMiddleware

# ── Config from environment (set in docker-compose.yml) ──────────────────────
def _base_url_from_env(primary: str, legacy: str, default: str) -> str:
    value = os.getenv(primary) or os.getenv(legacy) or default
    value = value.strip().rstrip("/")
    return value or default


AGENT_ENDPOINT = _base_url_from_env("AGENT_BASE_URL", "AGENT_ENDPOINT", "http://agent:9090")
GATEWAY_PORT   = int(os.getenv("GATEWAY_PORT", 8888))
SIMULATION_ENDPOINT = _base_url_from_env("SIMULATION_BASE_URL", "SIM_SERVICE_URL", "http://simulation:7000")

# ── Lifespan: probe all backends on container boot ────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await validate_on_startup()
    yield

app = FastAPI(
    title="AINN-CoPilot Gateway",
    description="OPEA MegaService gateway for AI-Native Network CoPilot",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# ── Request / Response schemas ────────────────────────────────────────────────
class QueryRequest(BaseModel):
    query: str
    thread_id: Optional[str] = None
    stream: bool = True
    request_id: Optional[str] = Field(None, max_length=128)
    simulation: Optional[dict] = None

class HealthResponse(BaseModel):
    status: str
    agent_reachable: bool

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/v1/health", response_model=HealthResponse)
async def health(response: Response = None):
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{AGENT_ENDPOINT}/v1/health_check")
            reachable = 200 <= r.status_code < 300
    except Exception:
        reachable = False
    if not reachable and response is not None:
        response.status_code = 503
    return HealthResponse(status="ok" if reachable else "degraded", agent_reachable=reachable)

# Docker/K8s/tools often expect /health. The actual gateway endpoint is /v1/health. 
# Supporting both is usefu
@app.get("/health", response_model=HealthResponse)
async def health_alias(response: Response):
    return await health(response)

# ── Agent + tools status ──────────────────────────────────────────────────────
@app.get("/v1/agent/status")
async def agent_status():
    """Returns opea/agent readiness + per-tool reachability + latency."""
    return await get_agent_status()

# ── Main chat endpoint (streaming) ────────────────────────────────────────────
@app.post("/v1/chat")
async def chat(req: QueryRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    gateway_request_id = f"gw-{uuid.uuid4()}"

    # Short-circuit: health-check intent never hits the LLM
    intent = classify_intent(req.query)
    if intent == IntentType.HEALTH_CHECK:
        status = await get_agent_status()
        healthy = status.opea_agent_ready and all(t.reachable for t in status.tools)
        tool_summary = [
            {"name": t.name, "reachable": t.reachable, "latency_ms": t.latency_ms}
            for t in status.tools
        ]
        return {
            "response": "✅ All systems operational." if healthy else "⚠️ Some backends are degraded.",
            "intent": intent,
            "thread_id": thread_id,
            "tools": tool_summary,
        }

    payload = {
        "messages": req.query,
        "thread_id": thread_id,
        "stream": req.stream,
        "request_id": gateway_request_id,
    }
    if req.simulation is not None:
        payload["simulation"] = req.simulation

    if req.stream:
        return StreamingResponse(
            _stream_from_agent(payload),
            media_type="text/event-stream",
            headers={
                "X-Thread-ID": thread_id,
                "X-Request-ID": gateway_request_id,
                "X-Intent": intent.value,
            },
        )
    else:
        return await _blocking_call(payload, gateway_request_id=gateway_request_id, thread_id=thread_id)


async def _job_proxy(method: str, path: str, payload=None):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(method, f"{AGENT_ENDPOINT}{path}", json=payload)
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Agent returned non-object JSON")
            return body
    except httpx.HTTPStatusError as error:
        try:
            detail = error.response.json().get("detail", error.response.text)
        except ValueError:
            detail = error.response.text[:1000]
        raise HTTPException(error.response.status_code, detail) from error
    except httpx.TimeoutException as error:
        raise HTTPException(504, "Agent job API timed out") from error
    except (httpx.RequestError, ValueError) as error:
        raise HTTPException(502, f"Agent job API unavailable: {error}") from error


@app.post("/v1/jobs", status_code=202)
async def create_job(req: QueryRequest):
    return await _job_proxy("POST", "/v1/jobs", {
        "messages": req.query, "thread_id": req.thread_id, "stream": False,
        "request_id": req.request_id or str(uuid.uuid4()), "simulation": req.simulation})


@app.get("/v1/jobs/{job_id}")
async def job_status(job_id: str):
    return await _job_proxy("GET", f"/v1/jobs/{job_id}")


@app.delete("/v1/jobs/{job_id}")
async def job_cancel(job_id: str):
    return await _job_proxy("DELETE", f"/v1/jobs/{job_id}")


@app.get("/v1/jobs/{job_id}/artifacts/{name}")
async def job_artifact(job_id: str, name: str):
    allowed = {"result.json", "result.sca", "result.vec", "request.ini", "engine.log"}
    if name not in allowed | {"candidate." + item for item in allowed} | {"reference.result.json"}:
        raise HTTPException(404, "Unknown artifact")
    job = await job_status(job_id)
    simulation_id = job.get("simulation_job_id")
    if not simulation_id:
        raise HTTPException(404, "This query has no live simulation artifacts")
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            response = await client.get(f"{SIMULATION_ENDPOINT}/jobs/{simulation_id}/artifacts/{name}")
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise HTTPException(error.response.status_code, "Artifact unavailable") from error
        except httpx.RequestError as error:
            raise HTTPException(502, "Simulation artifact service unavailable") from error
    return Response(response.content, media_type=response.headers.get("content-type", "application/octet-stream"),
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})

# ── Streaming helper ──────────────────────────────────────────────────────────
async def _stream_from_agent(payload: dict):
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{AGENT_ENDPOINT}/v1/chat/completions",
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        yield f"{line}\n\n"
    except httpx.HTTPStatusError as e:
        err = json.dumps({"error": str(e)})
        yield f"data: {err}\n\n"
    except Exception as e:
        err = json.dumps({"error": f"Gateway error: {str(e)}"})
        yield f"data: {err}\n\n"

# ── Non-streaming helper ──────────────────────────────────────────────────────
async def _blocking_call(payload: dict, gateway_request_id: str, thread_id: str) -> dict:
    payload["stream"] = False
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{AGENT_ENDPOINT}/v1/chat/completions",
                json=payload,
            )
            r.raise_for_status()
            body = r.json()
            if not isinstance(body, dict):
                raise ValueError("Agent returned non-object JSON")
            body.setdefault("gateway_request_id", gateway_request_id)
            body.setdefault("thread_id", thread_id)
            return body
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))
    except httpx.TimeoutException as e:
        raise HTTPException(status_code=504, detail=f"Agent request timed out: {e}") from e
    except (httpx.RequestError, ValueError) as e:
        raise HTTPException(status_code=502, detail=f"Agent response error: {e}") from e

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=GATEWAY_PORT)
