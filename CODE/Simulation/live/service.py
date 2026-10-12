"""HTTP jobs for fresh, isolated Simu5G baseline experiments."""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from common.jobs import JobConflict, JobQueue, QueueFull
from .run import experiment, time_series
from app.api.schemas import SimulationRequest
from app.simulator.replay_service import ReplayFixtureService, ReplayError, resolve_replay_fixture_for_scenario


DATA = Path(os.getenv("SIMULATION_DATA_DIRECTORY", "/data"))


class SimulationJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["baseline", "normal_operation", "traffic_burst", "resource_comparison", "mobility_handover"] = "baseline"
    mode: Literal["live"] = "live"
    ue_count: int = Field(10, ge=1, le=200, strict=True)
    duration: float = Field(10, ge=3, le=120, allow_inf_nan=False)
    seed: int = Field(42, ge=0, le=2147483647, strict=True)
    bands: int = Field(50, ge=5, le=100, strict=True)
    comparison_bands: int = Field(10, ge=5, le=100, strict=True)
    burst_multiplier: float = Field(4, ge=2, le=10, allow_inf_nan=False)
    speed_mps: float = Field(60, ge=1, le=100, allow_inf_nan=False)
    request_id: str | None = Field(None, max_length=128)


async def execute(record, cancellation):
    values = record["request"]
    def progress(snapshot):
        vector = DATA / "runs" / record["job_id"] / "result.vec"
        if vector.is_file() and values["scenario"] != "resource_comparison":
            try:
                snapshot["timeline"] = [item for item in time_series(vector, values["duration"], partial=True)
                                        if item["time_seconds"] <= snapshot["simulated_seconds"]]
            except (OSError, ValueError):
                pass
        jobs.update(record["job_id"], stage="simulating", **snapshot)
    jobs.update(record["job_id"], stage="simulating")
    # Shield the thread so shutdown can signal and join the child process safely.
    task = asyncio.create_task(asyncio.to_thread(
        experiment, **{key: values[key] for key in ("scenario", "ue_count", "duration", "seed", "bands", "comparison_bands", "burst_multiplier", "speed_mps")},
        timeout=float(os.getenv("SIMULATION_JOB_TIMEOUT_SECONDS", "300")),
        output_dir=str(DATA / "runs"), progress_callback=progress,
        cancel_event=cancellation, job_id=record["job_id"]))
    try:
        result = await asyncio.shield(task)
    except asyncio.CancelledError:
        cancellation.set()
        await asyncio.gather(task, return_exceptions=True)
        raise
    result["artifact_urls"] = {name: f"/jobs/{record['job_id']}/artifacts/{name}"
                               for name in ARTIFACTS if (DATA / "runs" / record["job_id"] / name).is_file()}
    return result


jobs = JobQueue(DATA / "jobs", execute, capacity=8)
ARTIFACTS = {"result.json", "result.sca", "result.vec", "request.ini", "engine.log"}
ARTIFACTS |= {"candidate." + name for name in tuple(ARTIFACTS)}
ARTIFACTS.add("reference.result.json")


@asynccontextmanager
async def lifespan(app):
    await jobs.start()
    yield
    await jobs.stop()


app = FastAPI(title="TelcoMind Live Simulation", lifespan=lifespan)


@app.post("/simulate")
def replay(request: SimulationRequest):
    if request.mode != "replay":
        raise HTTPException(409, "Fresh simulations use POST /jobs. Set mode=replay explicitly for recorded output.")
    try:
        fixture = resolve_replay_fixture_for_scenario(request.scenario, "phase_bootstrap_normal")
        result = ReplayFixtureService().replay(fixture, strict_checksums=True)
    except ReplayError as error:
        raise HTTPException(422, error.message) from error
    return {"status": "completed", "mode": "replay", "metrics": result["metrics"],
            "applied_parameters": result["recorded_fixture_parameters"],
            "unsupported_parameters": {key: "Recorded fixture output is unchanged by request parameters."
                                       for key in ("ue_count", "cell_id", "slice_type", "seed")},
            "result_reference": {"provenance": result["provenance"]}}


@app.get("/health")
def health():
    return {"status": "healthy", "process_liveness": True, "default_mode": "live"}


@app.get("/ready")
def ready():
    available = all(Path(path).is_file() for path in (
        "/opt/omnetpp/bin/opp_run", "/opt/inet/src/libINET.so", "/opt/simu5g/src/libsimu5g.so"))
    if not available:
        raise HTTPException(503, "Simulator toolchain is unavailable")
    return {"ready": True, "default_mode": "live", "live_enabled": True,
            "supported_scenarios": ["baseline", "normal_operation", "traffic_burst", "resource_comparison", "mobility_handover"],
            "cell_count": 7, "mobility": ["stationary", "linear"], "slice_support": False}


@app.post("/jobs", status_code=202)
async def submit(request: SimulationJobRequest):
    if request.scenario == "resource_comparison" and request.bands == request.comparison_bands:
        raise HTTPException(422, "Resource comparison requires two different band counts")
    try:
        return jobs.submit(request.model_dump(exclude={"request_id"}), request.request_id)
    except JobConflict as error:
        raise HTTPException(409, str(error)) from error
    except QueueFull as error:
        raise HTTPException(429, str(error), headers={"Retry-After": "5"}) from error


@app.get("/jobs/{job_id}")
def status(job_id: str):
    try:
        return jobs.get(job_id)
    except KeyError:
        raise HTTPException(404, "Unknown simulation job")


@app.delete("/jobs/{job_id}")
def cancel(job_id: str):
    status(job_id)
    return jobs.cancel(job_id)


@app.get("/jobs/{job_id}/artifacts/{name}")
def artifact(job_id: str, name: str):
    status(job_id)
    if name not in ARTIFACTS:
        raise HTTPException(404, "Unknown artifact")
    path = DATA / "runs" / job_id / name
    if not path.is_file():
        raise HTTPException(404, "Artifact is not available yet")
    return FileResponse(path, filename=name)
