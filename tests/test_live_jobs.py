import asyncio
import importlib
import json
from pathlib import Path
import sys

import pytest

CODE = Path(__file__).resolve().parents[1] / "CODE"
sys.path.insert(0, str(CODE))
sys.path.insert(0, str(CODE / "Agent"))
from common.jobs import JobConflict, JobQueue, QueueFull


def test_queue_deduplicates_and_limits_active_jobs(tmp_path):
    async def scenario():
        gate = asyncio.Event()
        async def handler(record, cancellation):
            await gate.wait()
            return {"value": record["request"]["value"]}
        queue = JobQueue(tmp_path, handler, capacity=1)
        await queue.start()
        try:
            first = queue.submit({"value": 1}, "same-request")
            assert queue.submit({"value": 1}, "same-request")["job_id"] == first["job_id"]
            with pytest.raises(JobConflict):
                queue.submit({"value": 2}, "same-request")
            with pytest.raises(QueueFull):
                queue.submit({"value": 2}, "other")
            gate.set()
            await queue.queue.join()
            assert queue.get(first["job_id"])["result"] == {"value": 1}
        finally:
            await queue.stop()
    asyncio.run(scenario())


def test_jobs_survive_restart_and_interrupted_work_is_failed(tmp_path):
    async def handler(record, cancellation):
        return {"measured": True}
    async def scenario():
        queue = JobQueue(tmp_path, handler)
        await queue.start()
        first = queue.submit({"value": 1})
        await queue.queue.join()
        await queue.stop()
        queued = dict(first, job_id="a" * 32, status="running")
        (tmp_path / (queued["job_id"] + ".json")).write_text(json.dumps(queued))
        restarted = JobQueue(tmp_path, handler)
        await restarted.start()
        try:
            assert restarted.get(first["job_id"])["result"] == {"measured": True}
            assert restarted.get("a" * 32)["status"] == "failed"
            with pytest.raises(KeyError):
                restarted.get("../escape")
        finally:
            await restarted.stop()
    asyncio.run(scenario())


def test_queued_cancel_never_executes_experiment(tmp_path):
    async def scenario():
        calls = []
        async def handler(record, cancellation):
            calls.append(record["job_id"])
            return {}
        queue = JobQueue(tmp_path, handler)
        await queue.start()
        try:
            job = queue.submit({})
            queue.cancel(job["job_id"])
            await queue.queue.join()
            assert queue.get(job["job_id"])["status"] == "cancelled"
            assert calls == []
        finally:
            await queue.stop()
    asyncio.run(scenario())


def test_live_routing_and_prompt_parameters(monkeypatch):
    monkeypatch.setenv("AGENT_SIMULATION_MODE", "live")
    service = importlib.reload(importlib.import_module("agent_service"))
    assert not service._needs_simulation("What causes handover failures in 5G NR according to 3GPP?")
    assert service._needs_simulation("Run a baseline simulation with 20 UEs")
    selected = service._select_simulation_request("Run a baseline with 20 UEs")
    assert selected["ue_count"] == 20 and selected["mode"] == "live"
    assert service._select_simulation_request("Run a replay baseline")["mode"] == "replay"
    assert service._select_simulation_request("Run a resource comparison")["scenario"] == "resource_comparison"
    assert service._select_simulation_request("Simulate a traffic burst")["scenario"] == "traffic_burst"
    assert service._select_simulation_request("Simulate mobility handovers")["scenario"] == "mobility_handover"
    assert service._select_simulation_request("Simulate interference")["scenario"] == "interference_hotspot"
    with pytest.raises(service.HTTPException) as error:
        asyncio.run(service.submit_job(service.ChatCompletionRequest(messages="Simulate handover failure")))
    assert error.value.status_code == 422
    monkeypatch.delenv("AGENT_SIMULATION_MODE")
    importlib.reload(service)


def test_synthesis_context_preserves_experiment_and_bounds_per_ue_details():
    service = importlib.import_module("agent_service")
    context = service._synthesis_context({
        "mode": "live", "scenario": "baseline", "ue_count": 2,
        "topology": {"mobility": "stationary"},
        "measurement": {"note": "Includes packets still in flight."},
        "per_ue": [{"throughput_mbps": 0.8, "latency_ms": 5.0},
                   {"throughput_mbps": 0.7, "latency_ms": 6.0}],
    })
    assert context["mobility"] == "stationary"
    assert context["per_ue_summary"]["throughput_mbps"] == {"min": 0.7, "max": 0.8, "count": 2}
    assert context["per_ue_summary"]["latency_ms"]["max"] == 6.0
    assert "per_ue" not in context
