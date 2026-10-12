#!/usr/bin/env python3
"""Exercise fresh burst, paired resource, and mobility jobs through the gateway."""

import argparse
import json
import time
import uuid

from smoke_live import request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8888")
    parser.add_argument("--ue-count", type=int, default=10)
    args = parser.parse_args()
    summaries = []
    for scenario in ("traffic_burst", "resource_comparison", "mobility_handover"):
        job = request("POST", args.base_url + "/v1/jobs", {
            "query": f"Simulate {scenario} with {args.ue_count} UEs and analyze measured results with citations.",
            "request_id": uuid.uuid4().hex,
            "simulation": {"mode": "live", "scenario": scenario, "duration": 10, "seed": 42}})
        deadline = time.monotonic() + 420
        while job["status"] not in {"completed", "failed", "cancelled"}:
            assert time.monotonic() < deadline, f"{scenario} timed out"
            time.sleep(0.3)
            job = request("GET", f"{args.base_url}/v1/jobs/{job['job_id']}")
        assert job["status"] == "completed", job.get("error")
        result = job["result"]
        simulation = result["simulation"]
        assert simulation["scenario"] == scenario and simulation["mode"] == "live"
        assert simulation["timeline"] and result["synthesis"]["citations"]
        if scenario == "traffic_burst":
            assert [phase["phase"] for phase in simulation["phases"]] == ["before", "burst", "after"]
            assert simulation["parameters"]["burst_multiplier"] == 4
        elif scenario == "resource_comparison":
            pair = simulation["comparison"]
            assert pair["reference"]["engine_run_id"] != pair["candidate"]["engine_run_id"]
            for key in ("ue_count", "seed", "duration_seconds"):
                assert pair["reference"][key] == pair["candidate"][key]
            assert pair["reference_bands"] == 50 and pair["candidate_bands"] == 10
            artifact = request("GET", f"{args.base_url}/v1/jobs/{job['job_id']}/artifacts/candidate.result.json")
            assert artifact["engine_run_id"] == pair["candidate"]["engine_run_id"]
        else:
            assert simulation["topology"]["mobility"] == "linear"
            assert simulation["handover"]["measured_ues"] == args.ue_count
            assert all(event["time_seconds"] > 0 for event in simulation["handover"]["events"])
            if args.ue_count == 10:
                assert simulation["handover"]["serving_cell_transitions"] > 0
        summary = {"scenario": scenario, "job_id": job["job_id"], "metrics": simulation["metrics"],
                   "transitions": simulation.get("handover", {}).get("serving_cell_transitions"),
                   "delta": simulation.get("comparison", {}).get("delta_candidate_minus_reference")}
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    print(json.dumps({"status": "PASS", "scenarios": len(summaries)}))


if __name__ == "__main__":
    main()
