#!/usr/bin/env python3
"""Host-side smoke test for the TelcoMind quickstart Compose stack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any


class CheckRunner:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.start = time.monotonic()
        self.seen_payloads: list[Any] = []

    def pass_(self, name: str) -> None:
        print(f"PASS {name}")

    def fail(self, name: str, message: str) -> None:
        self.failures.append(f"{name}: {message}")
        print(f"FAIL {name}: {message}")

    def require(self, name: str, condition: bool, message: str) -> None:
        if condition:
            self.pass_(name)
        else:
            self.fail(name, message)

    def record(self, payload: Any) -> None:
        self.seen_payloads.append(payload)

    def finish(self) -> int:
        elapsed = time.monotonic() - self.start
        if self.failures:
            print(f"SUMMARY FAIL checks_failed={len(self.failures)} duration_s={elapsed:.2f}")
            for failure in self.failures:
                print(f"ERROR {failure}")
            return 1
        print(f"SUMMARY PASS duration_s={elapsed:.2f}")
        return 0


def _request_json(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise AssertionError(f"{url} returned non-object JSON")
    return body


def _request_text(method: str, url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _assert_no_forbidden_network_or_claims(runner: CheckRunner) -> None:
    text = json.dumps(runner.seen_payloads, sort_keys=True)
    forbidden = {
        "Tailscale": "Tailscale dependency leaked into responses",
        "100.": "100.x private overlay URL leaked into responses",
        "live Simu5G": "default response claimed live Simu5G",
        '"llm_used": true': "default response claimed LLM use",
        '"score_type": "confidence"': "lexical ranking score was called confidence",
        "calibrated confidence": "lexical ranking was described as calibrated confidence",
    }
    for needle, message in forbidden.items():
        runner.require(f"network/default guard: {needle}", needle not in text, message)


def run(args: argparse.Namespace) -> int:
    timeout = args.timeout
    runner = CheckRunner()

    try:
        sim_health = _request_json("GET", f"{args.simulation_url}/health", None, timeout)
        runner.record(sim_health)
        runner.require(
            "simulation /health",
            sim_health.get("process_liveness") is True or sim_health.get("status") in {"healthy", "ok"},
            "unexpected liveness payload",
        )

        sim_ready = _request_json("GET", f"{args.simulation_url}/ready", None, timeout)
        runner.record(sim_ready)
        runner.require("simulation /ready replay", sim_ready.get("default_mode") == "replay", "default mode is not replay")
        runner.require("simulation live disabled", sim_ready.get("live_enabled") is False, "live mode is enabled")

        sim_response = _request_json(
            "POST",
            f"{args.simulation_url}/simulate",
            {
                "scenario": "baseline",
                "ue_count": 20,
                "cell_id": "cell-1",
                "slice_type": "eMBB",
                "mode": "replay",
            },
            timeout,
        )
        runner.record(sim_response)
        provenance = sim_response.get("result_reference", {}).get("provenance", {})
        runner.require("simulation completed", sim_response.get("status") == "completed", "simulation did not complete")
        runner.require("simulation mode replay", sim_response.get("mode") == "replay", "simulation mode is not replay")
        runner.require("simulation not live", provenance.get("live_simulation") is False, "simulation claimed live output")
        runner.require("simulation fixture provenance", bool(provenance.get("fixture_id")), "missing fixture provenance")
        runner.require("simulation metrics present", bool(sim_response.get("metrics")), "missing metrics")
        runner.require(
            "simulation unsupported parameters visible",
            bool(sim_response.get("unsupported_parameters")),
            "replay request-parameter limitations are not visible",
        )
    except Exception as exc:
        runner.fail("simulation checks", str(exc))

    retrieval: dict[str, Any] = {}
    synthesis: dict[str, Any] = {}
    try:
        rag_health = _request_json("GET", f"{args.rag_url}/health", None, timeout)
        runner.record(rag_health)
        runner.require("rag /health", rag_health.get("status") == "healthy", "unexpected RAG health")

        rag_ready = _request_json("GET", f"{args.rag_url}/ready", None, timeout)
        runner.record(rag_ready)
        runner.require("rag profile quickstart", rag_ready.get("rag_profile") == "quickstart", "RAG profile is not quickstart")
        runner.require("rag lexical backend", rag_ready.get("retrieval_backend") == "lexical_bm25", "RAG backend is not lexical")
        runner.require(
            "rag deterministic ready",
            rag_ready.get("synthesis", {}).get("deterministic_available") is True,
            "deterministic synthesis is not ready",
        )

        retrieval = _request_json(
            "POST",
            f"{args.rag_url}/v1/retrievaltool/json",
            {"text": "handover failure causes and mobility robustness in 5G NR", "top_k": 4},
            timeout,
        )
        runner.record(retrieval)
        sources = retrieval.get("sources", [])
        runner.require("rag result_count", retrieval.get("result_count", 0) > 0, "no retrieval results")
        runner.require("rag citations structured", bool(sources and sources[0].get("source")), "source metadata missing")
        runner.require(
            "rag score type raw",
            retrieval.get("raw", {}).get("score_type") != "confidence",
            "raw lexical score is labelled confidence",
        )
        runner.require("rag metadata profile", retrieval.get("rag_profile") == "quickstart", "retrieval profile mismatch")
        runner.require("rag metadata backend", retrieval.get("retrieval_backend") == "lexical_bm25", "retrieval backend mismatch")

        synthesis = _request_json(
            "POST",
            f"{args.rag_url}/synthesize",
            {
                "query": "Summarize likely handover failure causes.",
                "top_k": 4,
                "simulation_kpis": {"handover_success_rate": 0.72},
                "intent_type": "DIAGNOSTIC",
            },
            timeout,
        )
        runner.record(synthesis)
        runner.require("synthesis deterministic", synthesis.get("synthesis_backend") == "deterministic", "not deterministic")
        runner.require("synthesis no llm", synthesis.get("llm_used") is False, "LLM was used")
        runner.require("synthesis grounded citations", bool(synthesis.get("citations")), "citations missing")
        runner.require(
            "synthesis unknown citations checked",
            synthesis.get("unknown_citation_ids") == [] and synthesis.get("citation_validation") in {"passed", "warned"},
            "unknown citation handling failed",
        )
    except Exception as exc:
        runner.fail("rag checks", str(exc))

    try:
        agent_health = _request_json("GET", f"{args.agent_url}/v1/health_check", None, timeout)
        runner.record(agent_health)
        runner.require("agent /v1/health_check", agent_health.get("ready") is True, "agent is not ready")

        agent_response = _request_json(
            "POST",
            f"{args.agent_url}/v1/chat/completions",
            {
                "messages": "Run a baseline simulation with 20 UEs and cite likely handover failure causes.",
                "thread_id": "smoke-agent",
                "stream": False,
            },
            timeout,
        )
        runner.record(agent_response)
        evidence = agent_response.get("evidence", {})
        runner.require("agent reaches simulation", evidence.get("simulation_reached") is True, "simulation not reached")
        runner.require("agent reaches rag", evidence.get("rag_reached") is True, "RAG not reached")
        runner.require("agent preserves metadata", evidence.get("synthesis_backend") == "deterministic", "metadata missing")
        runner.require("agent status not hidden", agent_response.get("status") == "completed", "agent did not complete")
    except urllib.error.HTTPError as exc:
        runner.fail("agent checks", f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
    except Exception as exc:
        runner.fail("agent checks", str(exc))

    try:
        gateway_health = _request_json("GET", f"{args.gateway_url}/v1/health", None, timeout)
        runner.record(gateway_health)
        runner.require("gateway /v1/health", gateway_health.get("agent_reachable") is True, "agent is unreachable")

        gateway_response = _request_json(
            "POST",
            f"{args.gateway_url}/v1/chat",
            {
                "query": "Run a baseline simulation with 20 UEs and cite likely handover failure causes.",
                "thread_id": "smoke-gateway",
                "stream": False,
            },
            timeout,
        )
        runner.record(gateway_response)
        runner.require("gateway reaches agent", gateway_response.get("agent_profile") == "quickstart", "gateway response is not from agent")
        runner.require("gateway structure", bool(gateway_response.get("choices")), "gateway response missing choices")
    except urllib.error.HTTPError as exc:
        runner.fail("gateway checks", f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}")
    except Exception as exc:
        runner.fail("gateway checks", str(exc))

    try:
        status, _ = _request_text("GET", f"{args.ui_url}/healthz", timeout)
        runner.require("ui /healthz", 200 <= status < 300, f"UI returned HTTP {status}")
    except Exception as exc:
        runner.fail("ui checks", str(exc))

    _assert_no_forbidden_network_or_claims(runner)
    return runner.finish()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation-url", default=os.getenv("SMOKE_SIMULATION_URL", "http://localhost:7000").rstrip("/"))
    parser.add_argument("--rag-url", default=os.getenv("SMOKE_RAG_URL", "http://localhost:7001").rstrip("/"))
    parser.add_argument("--agent-url", default=os.getenv("SMOKE_AGENT_URL", "http://localhost:9090").rstrip("/"))
    parser.add_argument("--gateway-url", default=os.getenv("SMOKE_GATEWAY_URL", "http://localhost:8888").rstrip("/"))
    parser.add_argument("--ui-url", default=os.getenv("SMOKE_UI_URL", "http://localhost:8501").rstrip("/"))
    parser.add_argument("--timeout", type=float, default=float(os.getenv("SMOKE_TIMEOUT_SECONDS", "30")))
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
