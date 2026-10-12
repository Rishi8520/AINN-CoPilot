#!/usr/bin/env python3
"""Verify a browser-equivalent fresh simulation query through the gateway."""

import argparse
import json
import time
import urllib.request
import uuid


def request(method, url, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name, port in (("simulation", 7000), ("rag", 7001), ("agent", 9090), ("gateway", 8888), ("ui", 8501)):
        parser.add_argument(f"--{name}-url", default=f"http://localhost:{port}")
    args = parser.parse_args()
    capabilities = request("GET", f"{args.rag_url}/capabilities")
    required_opea = capabilities.get("configured_synthesis_backend") == "opea_agent"
    def verify_reasoning(result):
        if required_opea:
            synthesis = result["synthesis"]
            assert synthesis["synthesis_backend"] == "opea_agent", "OPEA was not used"
            assert synthesis["llm_used"] and not synthesis["fallback_used"]
            assert synthesis["citation_validation"] == "passed"
    ready = request("GET", f"{args.simulation_url}/ready")
    assert ready["default_mode"] == "live" and ready["ready"], ready
    payload = {"query": "Run a baseline simulation with 10 UEs and diagnose throughput and latency with citations.",
               "request_id": uuid.uuid4().hex, "simulation": {"mode": "live", "seed": 42, "duration": 10}}
    job = request("POST", f"{args.gateway_url}/v1/jobs", payload)
    duplicate = request("POST", f"{args.gateway_url}/v1/jobs", payload)
    assert duplicate["job_id"] == job["job_id"], "Duplicate submission created another experiment"
    deadline = time.monotonic() + 420
    stages = set()
    while job["status"] not in {"completed", "failed", "cancelled"}:
        assert time.monotonic() < deadline, "Gateway job timed out"
        stages.add(job["stage"])
        time.sleep(0.5)
        job = request("GET", f"{args.gateway_url}/v1/jobs/{job['job_id']}")
    assert job["status"] == "completed", job.get("error")
    result = job["result"]
    verify_reasoning(result)
    simulation = result["simulation"]
    assert simulation["mode"] == "live" and simulation["ue_count"] == 10
    assert simulation["engine_run_id"] and simulation["timeline"]
    assert len(simulation["per_ue"]) == 10 and simulation["topology"]["cell_count"] == 7
    assert simulation["metrics"]["throughput_mbps"] > 0
    assert result["synthesis"]["citations"], "Missing cited evidence"
    if result["synthesis"]["synthesis_backend"] == "deterministic":
        assert "Measured findings" in result["synthesis"]["answer"]
        assert "not a handover experiment" in result["synthesis"]["answer"]
        assert "Check handover" not in result["synthesis"]["recommended_action"]
    artifact = request("GET", f"{args.gateway_url}/v1/jobs/{job['job_id']}/artifacts/result.json")
    assert artifact["engine_run_id"] == simulation["engine_run_id"]
    standards = request("POST", f"{args.gateway_url}/v1/jobs", {
        "query": "What causes handover failures in 5G NR according to 3GPP?", "request_id": uuid.uuid4().hex})
    while standards["status"] not in {"completed", "failed", "cancelled"}:
        assert time.monotonic() < deadline, "Standards query timed out"
        time.sleep(0.2)
        standards = request("GET", f"{args.gateway_url}/v1/jobs/{standards['job_id']}")
    assert standards["status"] == "completed", standards.get("error")
    assert standards["result"]["evidence"]["simulation_reached"] is False
    verify_reasoning(standards["result"])
    definition = request("POST", f"{args.gateway_url}/v1/jobs", {
        "query": "What is O-RAN?", "request_id": uuid.uuid4().hex})
    while definition["status"] not in {"completed", "failed", "cancelled"}:
        assert time.monotonic() < deadline, "Definition query timed out"
        time.sleep(0.2)
        definition = request("GET", f"{args.gateway_url}/v1/jobs/{definition['job_id']}")
    assert definition["status"] == "completed", definition.get("error")
    assert definition["result"]["evidence"]["simulation_reached"] is False
    verify_reasoning(definition["result"])
    if definition["result"]["synthesis"]["synthesis_backend"] == "deterministic":
        assert "Open RAN" in definition["result"]["synthesis"]["answer"]
    assert definition["result"]["synthesis"]["recommended_action"] == ""
    with urllib.request.urlopen(f"{args.ui_url}/healthz", timeout=10) as response:
        assert response.status == 200
    print(json.dumps({"status": "PASS", "job_id": job["job_id"], "engine_run_id": simulation["engine_run_id"],
                      "metrics": simulation["metrics"], "stages_observed": sorted(stages),
                      "synthesis_backend": result["synthesis"]["synthesis_backend"],
                      "checks": ["fresh_simulation", "idempotency", "citations", "artifact_download",
                                 "standards_without_simulation", "baseline_diagnosis_limits",
                                 "oran_definition_without_remediation", "ui_health"]}, indent=2))


if __name__ == "__main__":
    main()
