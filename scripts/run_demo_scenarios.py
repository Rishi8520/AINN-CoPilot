#!/usr/bin/env python3
"""Run meaningful quickstart end-to-end demo scenarios through the real Gateway."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCENARIO_REQUIRED_FIELDS = {
    "id",
    "title",
    "purpose",
    "category",
    "gateway_request",
    "expected_services",
    "expected_http_status",
    "required_response_fields",
    "forbidden_claims",
    "expected_provenance",
    "expected_simulation_mode",
    "expected_rag_profile",
    "expected_retrieval_backend",
    "expected_synthesis_backend",
    "allow_empty_retrieval",
    "timeout_seconds",
    "destructive",
    "notes",
}

DEFAULT_SCENARIO_FILE = Path("demo/quickstart_scenarios.json")
DEFAULT_OUTPUT_DIR = Path("e2e-results")
DEFAULT_BASE_URL = "http://localhost:8888"
SAFE_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
URL_SECRET_PATTERNS = [
    re.compile(r"https?://[^\s/@:]+:[^\s/@]+@"),
    re.compile(r"(?i)(api[_-]?key|token|password|secret)=([^&\s]+)"),
]
ABS_PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\\\Users\\\\[^\s\"]+"),
    re.compile(r"/Users/[^\s\"]+"),
    re.compile(r"/home/[^\s\"]+"),
]
FORBIDDEN_POSITIVE_CLAIMS = [
    "live simu5g executed",
    "semantic retrieval was used",
    "semantic/vector retrieval was used",
    "gpu inference occurred",
    "an llm produced the response",
    "corrective action was executed on a real telecom network",
    "unsupported fault scenario was simulated",
]


class ScenarioError(RuntimeError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def find_repo_root(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "docker-compose.yml").exists() and (candidate / DEFAULT_SCENARIO_FILE).exists():
            return candidate
    raise ScenarioError("Could not find repository root containing docker-compose.yml and demo/quickstart_scenarios.json")


def relpath(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _json_request(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> tuple[int, dict[str, Any], str]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body_text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body_text = exc.read().decode("utf-8", errors="replace")
    parsed: dict[str, Any]
    try:
        obj = json.loads(body_text) if body_text.strip() else {}
        parsed = obj if isinstance(obj, dict) else {"_raw": obj}
    except json.JSONDecodeError:
        parsed = {"_non_json": body_text[:4000]}
    return status, parsed, body_text


def _request_text(method: str, url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url=url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def _safe_base_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    if not parsed.hostname:
        return False
    return parsed.hostname in SAFE_LOCAL_HOSTS


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in URL_SECRET_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    for pattern in ABS_PATH_PATTERNS:
        redacted = pattern.sub("<redacted_path>", redacted)
    redacted = redacted.replace(str(Path.home()), "<redacted_home>")
    return redacted


def _redact_obj(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if any(token in key_l for token in ["authorization", "api_key", "token", "password", "secret"]):
                out[key] = "<redacted>"
            else:
                out[key] = _redact_obj(item)
        return out
    if isinstance(value, list):
        return [_redact_obj(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


def _contains_positive_claim(text: str, claim: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower())
    target = claim.lower()
    idx = normalized.find(target)
    if idx < 0:
        return False
    window = normalized[max(0, idx - 30):idx]
    negations = [" not ", " no ", " never ", " without ", " did not ", " was not ", " false"]
    return not any(token in window for token in negations)


def _assert_no_leaks(payload: Any) -> None:
    text = json.dumps(payload, sort_keys=True)
    _assert("tailscale" not in text.lower(), "Response leaked a Tailscale claim")
    _assert(re.search(r"https?://100\.\d{1,3}\.\d{1,3}\.\d{1,3}", text) is None, "Response leaked a 100.x URL")
    for pattern in ABS_PATH_PATTERNS:
        _assert(pattern.search(text) is None, "Response leaked an absolute local path")


def _assert_required_fields(payload: dict[str, Any], required_fields: list[str]) -> None:
    for field in required_fields:
        _assert(field in payload, f"Missing required response field: {field}")


def _nested_get(payload: dict[str, Any], dotted: str) -> Any:
    current: Any = payload
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _assert_gateway_agent_structure(payload: dict[str, Any], expected_status: int) -> None:
    if expected_status >= 400:
        return
    _assert(isinstance(payload.get("choices"), list), "choices must be a list")
    _assert(isinstance(payload.get("evidence"), dict), "evidence must be an object")
    _assert(payload.get("evidence", {}).get("simulation_reached") is True, "Agent did not mark simulation_reached=true")
    _assert(payload.get("evidence", {}).get("rag_reached") is True, "Agent did not mark rag_reached=true")
    _assert(bool(payload.get("id")), "Missing agent response id")


def _assert_simulation_structure(payload: dict[str, Any], scenario: dict[str, Any]) -> None:
    if scenario["expected_http_status"] >= 400:
        return
    simulation = payload.get("simulation", {})
    evidence = payload.get("evidence", {})
    result_ref = simulation.get("result_reference", {})
    provenance = result_ref.get("provenance", {})

    _assert(simulation.get("mode") == scenario["expected_simulation_mode"], "Simulation mode mismatch")
    _assert(evidence.get("simulation_mode") == scenario["expected_simulation_mode"], "Evidence simulation mode mismatch")
    _assert(simulation.get("status") == "completed", "Simulation did not complete")
    _assert(result_ref.get("live_simulation") is False, "Simulation response did not stay in replay mode")
    _assert(bool(simulation.get("metrics")), "Simulation metrics are empty")
    _assert(bool(simulation.get("unsupported_parameters")), "Replay unsupported parameter metadata missing")
    _assert(bool(simulation.get("run_id")), "Simulation run_id missing")
    _assert(str(simulation.get("run_id", "")).startswith("replay-"), "Replay run_id is not clearly replay-prefixed")

    expected_prov = scenario.get("expected_provenance", {})
    if "fixture_id" in expected_prov:
        _assert(provenance.get("fixture_id") == expected_prov["fixture_id"], "Replay fixture_id mismatch")
    if "mode_label" in expected_prov:
        _assert(result_ref.get("mode_label") == expected_prov["mode_label"], "Simulation mode_label mismatch")
    if "checksums_verified" in expected_prov:
        _assert(provenance.get("checksums_verified") is expected_prov["checksums_verified"], "Checksum metadata mismatch")
    if "created_from_existing_repository_artifact" in expected_prov:
        _assert(
            provenance.get("created_from_existing_repository_artifact") is expected_prov["created_from_existing_repository_artifact"],
            "Simulation fixture provenance origin mismatch",
        )


def _assert_rag_structure(payload: dict[str, Any], scenario: dict[str, Any]) -> dict[str, Any]:
    if scenario["expected_http_status"] >= 400:
        return {}
    rag = payload.get("rag", {})
    sources = rag.get("sources", [])

    _assert(rag.get("rag_profile") == scenario["expected_rag_profile"], "RAG profile mismatch")
    _assert(rag.get("retrieval_backend") == scenario["expected_retrieval_backend"], "RAG retrieval backend mismatch")
    _assert(rag.get("result_count") == len(sources), "RAG result_count does not match sources length")

    raw_score_type = str(rag.get("raw", {}).get("score_type") or "").lower()
    _assert("confidence" not in raw_score_type, "BM25 score was labelled confidence")
    _assert("probability" not in raw_score_type, "BM25 score was labelled probability")

    allow_empty = bool(scenario.get("allow_empty_retrieval"))
    if not allow_empty:
        _assert(rag.get("result_count", 0) > 0, "Expected non-empty retrieval for this scenario")
    else:
        _assert(rag.get("result_count", 0) >= 0, "Invalid no-match response")

    expected_types = set(scenario.get("expected_source_types", []))
    observed_types = {src.get("source_type") for src in sources if isinstance(src, dict)}
    if expected_types:
        _assert(bool(observed_types.intersection(expected_types)), "Expected source_type evidence was not retrieved")

    allowlisted = set(scenario.get("allowlisted_chunk_ids", []))
    if allowlisted and sources:
        retrieved_ids = {src.get("id") for src in sources if isinstance(src, dict)}
        _assert(bool(retrieved_ids.intersection(allowlisted)), "No allowlisted citation chunk id retrieved")

    for src in sources:
        if not isinstance(src, dict):
            continue
        for field in ["source", "title", "section", "chunk", "page", "kind", "source_type"]:
            _assert(field in src, f"Citation source missing structured field: {field}")

    return rag


def _assert_synthesis_structure(payload: dict[str, Any], scenario: dict[str, Any], rag: dict[str, Any]) -> None:
    if scenario["expected_http_status"] >= 400:
        return
    synthesis = payload.get("synthesis", {})
    rag_sources = rag.get("sources", []) if isinstance(rag, dict) else []

    _assert(synthesis.get("synthesis_backend") == scenario["expected_synthesis_backend"], "Synthesis backend mismatch")
    _assert(synthesis.get("llm_used") is False, "Synthesis incorrectly claims llm_used=true")
    _assert(synthesis.get("fallback_used") is False, "Synthesis unexpectedly used fallback")
    _assert(synthesis.get("unknown_citation_ids") in ([], None), "Unknown citation IDs were silently accepted")

    source_keys = {
        (src.get("source"), src.get("title"), src.get("section"), src.get("chunk"), src.get("page"), src.get("kind"), src.get("source_type"))
        for src in rag_sources
        if isinstance(src, dict)
    }
    for citation in synthesis.get("citations", []):
        if not isinstance(citation, dict):
            continue
        key = (
            citation.get("source"),
            citation.get("title"),
            citation.get("section"),
            citation.get("chunk"),
            citation.get("page"),
            citation.get("kind"),
            citation.get("source_type"),
        )
        _assert(key in source_keys, "Synthesis citation did not originate from retrieval sources")

    text = json.dumps(synthesis, sort_keys=True).lower()
    _assert("vllm" not in text, "Response incorrectly claims vLLM usage")
    _assert("openai" not in text, "Response incorrectly claims OpenAI usage")
    _assert("gpu" not in text, "Response incorrectly claims GPU usage")
    _assert("model generation" not in text, "Response incorrectly claims model generation")


def _assert_forbidden_claims(payload: dict[str, Any], scenario: dict[str, Any]) -> None:
    text = json.dumps(payload, sort_keys=True)
    for claim in [*FORBIDDEN_POSITIVE_CLAIMS, *scenario.get("forbidden_claims", [])]:
        if _contains_positive_claim(text, claim):
            raise ScenarioError(f"Forbidden positive claim detected: {claim}")


def _assert_unsupported_fault_not_masked(payload: dict[str, Any], scenario: dict[str, Any], status_code: int) -> None:
    if scenario["id"] != "unsupported_replay_fault":
        return
    if status_code >= 400:
        return
    sim = payload.get("simulation", {})
    scenario_asked = str(scenario.get("gateway_request", {}).get("query", "")).lower()
    if "handover_failure" in scenario_asked and sim.get("status") == "completed":
        requested = sim.get("requested_parameters", {}).get("scenario")
        fixture = sim.get("applied_parameters", {}).get("fixture_id")
        if requested in {"baseline", "normal", "normal_operation", "bootstrap_normal", "phase_bootstrap_normal"}:
            raise ScenarioError(
                "Unsupported replay fault request was masked by healthy baseline replay metrics."
            )
        if fixture == "phase_bootstrap_normal":
            raise ScenarioError(
                "Unsupported replay fault request returned healthy phase_bootstrap_normal fixture metrics."
            )


def _compare_repeatability(results: list[dict[str, Any]]) -> None:
    _assert(len(results) >= 2, "Repeatability scenario requires at least two runs")
    first = results[0]["body"]
    second = results[1]["body"]

    def fingerprint(body: dict[str, Any]) -> dict[str, Any]:
        sim = body.get("simulation", {})
        rag = body.get("rag", {})
        synthesis = body.get("synthesis", {})
        return {
            "simulation_mode": sim.get("mode"),
            "fixture_id": sim.get("result_reference", {}).get("provenance", {}).get("fixture_id"),
            "mode_label": sim.get("result_reference", {}).get("mode_label"),
            "rag_profile": rag.get("rag_profile"),
            "retrieval_backend": rag.get("retrieval_backend"),
            "source_ids": sorted(src.get("id") for src in rag.get("sources", []) if isinstance(src, dict)),
            "synthesis_backend": synthesis.get("synthesis_backend"),
            "llm_used": synthesis.get("llm_used"),
            "citation_ids": sorted(
                c.get("citation_id") for c in synthesis.get("citations", []) if isinstance(c, dict) and c.get("citation_id")
            ),
        }

    _assert(fingerprint(first) == fingerprint(second), "Repeatability structural fingerprint changed across runs")


def _current_commit(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _compose_ps(root: Path) -> tuple[list[dict[str, Any]], str]:
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(root), "ps", "--format", "json"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return [], result.stderr.strip() or result.stdout.strip()
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows, ""


def _stack_health(root: Path, base_url: str, timeout: float) -> dict[str, Any]:
    rows, compose_error = _compose_ps(root)
    health_rows = []
    for row in rows:
        health_rows.append(
            {
                "service": row.get("Service") or row.get("Name"),
                "state": row.get("State"),
                "health": row.get("Health"),
                "publishers": row.get("Publishers"),
            }
        )

    gw_status, gw_body, _ = _json_request("GET", f"{base_url}/v1/health", None, timeout)
    ag_status, ag_body, _ = _json_request("GET", f"{base_url}/v1/agent/status", None, timeout)

    running = [row for row in health_rows if row.get("state") == "running"]
    healthy = [row for row in health_rows if row.get("health") in {"healthy", ""}]

    return {
        "compose_services": health_rows,
        "compose_error": compose_error,
        "gateway_health_status": gw_status,
        "gateway_health": gw_body,
        "agent_status_http": ag_status,
        "agent_status": ag_body,
        "healthy_enough": bool(health_rows) and len(running) == len(health_rows) and len(healthy) == len(health_rows) and gw_status == 200,
    }


def _load_scenarios(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    _assert(isinstance(payload, dict), "Scenario file must be an object")
    scenarios = payload.get("scenarios")
    _assert(isinstance(scenarios, list) and scenarios, "Scenario file must contain a non-empty scenarios list")

    seen: set[str] = set()
    for scenario in scenarios:
        _assert(isinstance(scenario, dict), "Each scenario must be an object")
        missing = sorted(SCENARIO_REQUIRED_FIELDS - set(scenario))
        _assert(not missing, f"Scenario {scenario.get('id', '<unknown>')} missing fields: {missing}")
        sid = str(scenario["id"])
        _assert(sid not in seen, f"Duplicate scenario id: {sid}")
        seen.add(sid)
        _assert(isinstance(scenario.get("gateway_request"), dict), f"{sid}: gateway_request must be an object")

        dump = json.dumps(scenario, sort_keys=True)
        for pattern in ABS_PATH_PATTERNS:
            _assert(pattern.search(dump) is None, f"{sid}: scenario contains absolute local path")
        for pattern in URL_SECRET_PATTERNS:
            _assert(pattern.search(dump) is None, f"{sid}: scenario appears to contain secret material")
        if "http://" in dump or "https://" in dump:
            if not any(host in dump for host in SAFE_LOCAL_HOSTS):
                raise ScenarioError(f"{sid}: scenario appears to target an external URL")
        if "expected_prose" in dump.lower() or "exact answer" in dump.lower():
            raise ScenarioError(f"{sid}: scenario includes exact prose expectation, which is forbidden")

    return payload


def _scenario_log_paths(output_dir: Path, scenario_id: str) -> tuple[Path, Path]:
    json_path = output_dir / "logs" / f"{scenario_id}.json"
    text_path = output_dir / "logs" / f"{scenario_id}.log"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    return json_path, text_path


def _write_scenario_log(output_dir: Path, scenario_id: str, record: dict[str, Any]) -> None:
    json_path, text_path = _scenario_log_paths(output_dir, scenario_id)
    safe_record = _redact_obj(record)
    json_path.write_text(json.dumps(safe_record, indent=2, sort_keys=True), encoding="utf-8")
    lines = [
        f"scenario: {scenario_id}",
        f"status: {record.get('status')}",
        f"http_status: {record.get('http_status')}",
        f"duration_seconds: {record.get('duration_seconds')}",
    ]
    error = record.get("error")
    if error:
        lines.append(f"error: {_redact_text(str(error))}")
    text_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run_gateway_scenario(base_url: str, scenario: dict[str, Any], timeout: float) -> dict[str, Any]:
    request_payload = scenario["gateway_request"]
    started = time.monotonic()
    status_code, body, raw = _json_request("POST", f"{base_url}/v1/chat", request_payload, timeout)
    duration = round(time.monotonic() - started, 3)

    record = {
        "scenario_id": scenario["id"],
        "request": request_payload,
        "http_status": status_code,
        "body": body,
        "raw_response_excerpt": _redact_text(raw[:4000]),
        "duration_seconds": duration,
    }
    return record


def _validate_scenario_result(scenario: dict[str, Any], record: dict[str, Any]) -> None:
    status_code = record["http_status"]
    body = record["body"]
    expected_status = int(scenario["expected_http_status"])

    _assert(status_code == expected_status, f"Expected HTTP {expected_status}, got HTTP {status_code}")
    _assert(isinstance(body, dict), "Gateway response body is not an object")
    _assert_required_fields(body, scenario["required_response_fields"])
    _assert_no_leaks(body)
    _assert_gateway_agent_structure(body, expected_status)

    rag = _assert_rag_structure(body, scenario)
    _assert_simulation_structure(body, scenario)
    _assert_synthesis_structure(body, scenario, rag)
    _assert_forbidden_claims(body, scenario)
    _assert_unsupported_fault_not_masked(body, scenario, status_code)


def _service_log_snapshot(root: Path, service: str, output_file: Path) -> None:
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(root), "logs", "--no-color", service],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(_redact_text(result.stdout[-30000:]), encoding="utf-8")


def _wait_service_healthy(root: Path, service: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows, _ = _compose_ps(root)
        for row in rows:
            name = row.get("Service") or row.get("Name")
            if name == service:
                state = str(row.get("State") or "")
                health = str(row.get("Health") or "")
                if state == "running" and (health == "healthy" or not health):
                    return True
        time.sleep(2.0)
    return False


def _compose_service(root: Path, action: str, service: str) -> tuple[int, str]:
    result = subprocess.run(
        ["docker", "compose", "--project-directory", str(root), action, service],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


def _failure_injection(root: Path, base_url: str, timeout: float, output_dir: Path, verbose: bool) -> dict[str, Any]:
    outcomes: dict[str, Any] = {"enabled": True, "checks": []}

    def run_case(service: str, probe_scenario: dict[str, Any], restore_check_scenario: dict[str, Any], must_not_succeed: str) -> None:
        case: dict[str, Any] = {"service": service, "stopped": False, "restored": False, "recovery_passed": False}
        try:
            rc, out = _compose_service(root, "stop", service)
            case["stop_returncode"] = rc
            case["stop_output"] = _redact_text(out[-2000:])
            _assert(rc == 0, f"Failed to stop {service}")
            case["stopped"] = True

            record = _run_gateway_scenario(base_url, probe_scenario, timeout)
            case["probe"] = _redact_obj(record)
            if record["http_status"] == 200:
                body = record["body"]
                ok = body.get("status") == "completed" and body.get("evidence", {}).get("rag_reached") is True
                _assert(not ok, must_not_succeed)
            case["dependency_failure_visible"] = True
        finally:
            try:
                rc, out = _compose_service(root, "start", service)
                case["start_returncode"] = rc
                case["start_output"] = _redact_text(out[-2000:])
                if rc == 0 and _wait_service_healthy(root, service, timeout=120):
                    case["restored"] = True
                    verify = _run_gateway_scenario(base_url, restore_check_scenario, timeout)
                    try:
                        _validate_scenario_result(restore_check_scenario, verify)
                        case["recovery_passed"] = True
                    except Exception as exc:
                        case["recovery_error"] = str(exc)
                else:
                    case["restore_error"] = f"Service {service} did not return healthy"
            except Exception as exc:
                case["restore_error"] = str(exc)
            _service_log_snapshot(root, service, output_dir / "logs" / f"failure_injection_{service}.log")
        outcomes["checks"].append(case)

    # Identify stable scenarios by id.
    scenarios = _load_scenarios(root / DEFAULT_SCENARIO_FILE)["scenarios"]
    by_id = {item["id"]: item for item in scenarios}
    baseline = by_id["grounded_diagnosis"]

    run_case(
        service="rag",
        probe_scenario=baseline,
        restore_check_scenario=baseline,
        must_not_succeed="RAG outage still returned successful grounded answer",
    )
    run_case(
        service="simulation",
        probe_scenario=baseline,
        restore_check_scenario=baseline,
        must_not_succeed="Simulation outage still returned successful replay KPI response",
    )

    # No-LLM check in default deterministic profile.
    llm_record = _run_gateway_scenario(base_url, baseline, timeout)
    llm_body = llm_record.get("body", {})
    _assert(llm_body.get("synthesis", {}).get("llm_used") is False, "Deterministic path unexpectedly used an LLM")
    outcomes["checks"].append(
        {
            "service": "llm",
            "stopped": False,
            "restored": True,
            "recovery_passed": True,
            "llm_used": llm_body.get("synthesis", {}).get("llm_used"),
            "synthesis_backend": llm_body.get("synthesis", {}).get("synthesis_backend"),
        }
    )

    if verbose:
        print("[failure-injection] completed checks:", len(outcomes["checks"]))
    return outcomes


def _scenario_ids_to_run(all_scenarios: list[dict[str, Any]], one: str | None, include_destructive: bool) -> list[dict[str, Any]]:
    if one:
        selected = [scenario for scenario in all_scenarios if scenario["id"] == one]
        if not selected:
            raise ScenarioError(f"Scenario id not found: {one}")
        return selected
    selected = []
    for scenario in all_scenarios:
        if scenario.get("destructive") and not include_destructive:
            continue
        selected.append(scenario)
    return selected


def _validate_base_url_or_raise(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        normalized = DEFAULT_BASE_URL
    if not _safe_base_url(normalized):
        raise ScenarioError(
            "Base URL is not local/safe. Only localhost, 127.0.0.1, ::1, or host.docker.internal are allowed."
        )
    return normalized


def _resolve_output_dir(root: Path, user_output_dir: str) -> Path:
    base = (root / DEFAULT_OUTPUT_DIR).resolve()
    requested = Path(user_output_dir)
    if requested.is_absolute():
        resolved = requested.resolve()
    else:
        resolved = (root / requested).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ScenarioError("Output directory must be inside e2e-results/.") from exc
    return resolved


def _citation_source_type_counts(scenario_records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in scenario_records:
        body = record.get("body", {})
        rag = body.get("rag", {})
        for src in rag.get("sources", []):
            if not isinstance(src, dict):
                continue
            stype = src.get("source_type") or "unknown"
            counts[stype] = counts.get(stype, 0) + 1
    return counts


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# TelcoMind Demo Scenario Summary",
        "",
        f"- Start: {summary['start_time_utc']}",
        f"- End: {summary['end_time_utc']}",
        f"- Duration (s): {summary['duration_seconds']}",
        f"- Git commit: {summary['git_commit']}",
        f"- Base URL: {summary['base_url']}",
        f"- Scenarios: total={summary['scenario_counts']['total']} pass={summary['scenario_counts']['pass']} fail={summary['scenario_counts']['fail']}",
        f"- Active Simulation mode: {summary['active_defaults'].get('simulation_mode')}",
        f"- Active RAG profile/backend: {summary['active_defaults'].get('rag_profile')} / {summary['active_defaults'].get('retrieval_backend')}",
        f"- Active synthesis backend: {summary['active_defaults'].get('synthesis_backend')}",
        f"- Replay fixture: {summary['active_defaults'].get('replay_fixture_id')}",
        "",
        "## Scenarios",
    ]
    for scenario in summary["scenarios"]:
        lines.append(
            f"- {scenario['scenario_id']}: {scenario['status']} "
            f"http={scenario['http_status']} duration={scenario['duration_seconds']}s"
        )
        if scenario.get("error"):
            lines.append(f"  error: {_redact_text(str(scenario['error']))}")
    lines.extend(
        [
            "",
            "## Notes",
            "- Timings in this report are functional execution timings, not formal performance evidence.",
            "- Replay output is recorded fixture output, not a newly executed live Simu5G run.",
            "- Deterministic synthesis is not an LLM generation path.",
            "- Lexical BM25 retrieval is not semantic/vector retrieval.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List scenarios and exit")
    parser.add_argument("--scenario", help="Run only one scenario id")
    parser.add_argument("--with-failure-injection", action="store_true", help="Enable destructive dependency-stop checks")
    parser.add_argument("--json-only", action="store_true", help="Print only JSON summary to stdout")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose progress output")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Gateway base URL")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Output directory for logs and summaries")
    parser.add_argument("--timeout", type=float, default=45.0, help="Default per-request timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = find_repo_root(Path(__file__).resolve())
    scenario_file = root / DEFAULT_SCENARIO_FILE
    scenario_data = _load_scenarios(scenario_file)
    all_scenarios = scenario_data["scenarios"]

    if args.list:
        for scenario in all_scenarios:
            print(f"{scenario['id']}\t{scenario['category']}\t{'destructive' if scenario.get('destructive') else 'safe'}\t{scenario['title']}")
        return 0

    base_url = _validate_base_url_or_raise(args.base_url)

    output_dir = _resolve_output_dir(root, args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "logs").mkdir(parents=True, exist_ok=True)

    start_utc = utc_now()
    start_time = time.monotonic()

    health = _stack_health(root, base_url, timeout=min(args.timeout, 10.0))
    if not health["healthy_enough"]:
        raise ScenarioError(
            "Stack health precheck failed. Ensure root compose stack is running and healthy before running scenarios."
        )

    selected = _scenario_ids_to_run(
        all_scenarios,
        one=args.scenario,
        include_destructive=bool(args.with_failure_injection),
    )

    scenario_records: list[dict[str, Any]] = []
    failures = 0

    for scenario in selected:
        scenario_timeout = float(scenario.get("timeout_seconds") or args.timeout)
        repeat = int(scenario.get("repeat") or 1)
        run_records: list[dict[str, Any]] = []
        for run_index in range(1, repeat + 1):
            if args.verbose:
                print(f"[run] {scenario['id']} ({run_index}/{repeat})")
            record = _run_gateway_scenario(base_url, scenario, timeout=min(scenario_timeout, args.timeout))
            record["run_index"] = run_index
            try:
                _validate_scenario_result(scenario, record)
                record["status"] = "PASS"
            except Exception as exc:
                record["status"] = "FAIL"
                record["error"] = str(exc)
                record["traceback"] = traceback.format_exc(limit=2)
            run_records.append(record)
            _write_scenario_log(output_dir, f"{scenario['id']}-run{run_index}", record)

        consolidated = run_records[-1]
        consolidated["scenario_id"] = scenario["id"]
        consolidated["runs"] = run_records

        if scenario["id"] == "deterministic_repeatability":
            try:
                _compare_repeatability(run_records)
            except Exception as exc:
                consolidated["status"] = "FAIL"
                consolidated["error"] = str(exc)

        if any(item["status"] == "FAIL" for item in run_records):
            consolidated["status"] = "FAIL"

        scenario_records.append(consolidated)
        if consolidated["status"] != "PASS":
            failures += 1

    failure_injection = {"enabled": False, "checks": []}
    if args.with_failure_injection:
        try:
            failure_injection = _failure_injection(root, base_url, timeout=args.timeout, output_dir=output_dir, verbose=args.verbose)
            for check in failure_injection.get("checks", []):
                if not check.get("restored") or not check.get("recovery_passed"):
                    failures += 1
        except Exception as exc:
            failure_injection = {
                "enabled": True,
                "error": str(exc),
                "checks": failure_injection.get("checks", []),
            }
            failures += 1

    end_utc = utc_now()
    duration = round(time.monotonic() - start_time, 3)

    active_defaults = {
        "simulation_mode": _nested_get(scenario_records[0].get("body", {}), "simulation.mode") if scenario_records else None,
        "replay_fixture_id": _nested_get(scenario_records[0].get("body", {}), "simulation.result_reference.provenance.fixture_id") if scenario_records else None,
        "rag_profile": _nested_get(scenario_records[0].get("body", {}), "rag.rag_profile") if scenario_records else None,
        "retrieval_backend": _nested_get(scenario_records[0].get("body", {}), "rag.retrieval_backend") if scenario_records else None,
        "synthesis_backend": _nested_get(scenario_records[0].get("body", {}), "synthesis.synthesis_backend") if scenario_records else None,
    }

    summary = {
        "schema_version": 1,
        "start_time_utc": start_utc,
        "end_time_utc": end_utc,
        "duration_seconds": duration,
        "git_commit": _current_commit(root),
        "base_url": base_url,
        "compose_health": _redact_obj(health),
        "scenario_counts": {
            "total": len(scenario_records),
            "pass": len([item for item in scenario_records if item.get("status") == "PASS"]),
            "fail": len([item for item in scenario_records if item.get("status") != "PASS"]),
        },
        "active_defaults": active_defaults,
        "citation_source_type_counts": _citation_source_type_counts(scenario_records),
        "failure_injection": _redact_obj(failure_injection),
        "functional_timing_note": "Timings are functional execution timings, not formal performance evidence.",
        "scenarios": [
            {
                "scenario_id": item["scenario_id"],
                "status": item.get("status"),
                "http_status": item.get("http_status"),
                "duration_seconds": item.get("duration_seconds"),
                "error": item.get("error"),
                "log_json": relpath(_scenario_log_paths(output_dir, f"{item['scenario_id']}-run{item.get('run_index', 1)}")[0], root),
                "log_text": relpath(_scenario_log_paths(output_dir, f"{item['scenario_id']}-run{item.get('run_index', 1)}")[1], root),
            }
            for item in scenario_records
        ],
    }

    (output_dir / "summary.json").write_text(json.dumps(_redact_obj(summary), indent=2, sort_keys=True), encoding="utf-8")
    (output_dir / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")

    if args.json_only:
        print(json.dumps(_redact_obj(summary), indent=2, sort_keys=True))
    else:
        print(_summary_markdown(summary))

    return 1 if failures else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ScenarioError as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(2)
