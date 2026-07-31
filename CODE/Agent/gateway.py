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
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
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

class HealthResponse(BaseModel):
    status: str
    agent_reachable: bool

# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/v1/health", response_model=HealthResponse)
async def health():
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{AGENT_ENDPOINT}/v1/health_check")
            reachable = 200 <= r.status_code < 300
    except Exception:
        reachable = False
    return HealthResponse(status="ok", agent_reachable=reachable)

# Docker/K8s/tools often expect /health. The actual gateway endpoint is /v1/health. 
# Supporting both is usefu
@app.get("/health", response_model=HealthResponse)
async def health_alias():
    return await health()

# ── Agent + tools status ──────────────────────────────────────────────────────
@app.get("/v1/agent/status")
async def agent_status():
    """Returns opea/agent readiness + per-tool reachability + latency."""
    return await get_agent_status()

# ── Main chat endpoint (streaming) ────────────────────────────────────────────
@app.post("/v1/chat")
async def chat(req: QueryRequest):
    thread_id = req.thread_id or str(uuid.uuid4())

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
    }

    if req.stream:
        return StreamingResponse(
            _stream_from_agent(payload),
            media_type="text/event-stream",
            headers={
                "X-Thread-ID": thread_id,
                "X-Intent": intent.value,
            },
        )
    else:
        return await _blocking_call(payload)

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
async def _blocking_call(payload: dict) -> dict:
    payload["stream"] = False
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{AGENT_ENDPOINT}/v1/chat/completions",
                json=payload,
            )
            r.raise_for_status()
            return r.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=str(e))

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=GATEWAY_PORT)
