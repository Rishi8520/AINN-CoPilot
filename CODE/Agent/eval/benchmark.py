import os
import json
import time
import uuid
import statistics
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env"))

#AGENT_URL = os.environ.get("AGENT_URL", "http://localhost:9090")
GATEWAY_URL = (os.environ.get("GATEWAY_BASE_URL") or os.environ.get("GATEWAY_URL") or "http://localhost:8888").rstrip("/")
# ─────────────────────────────────────────────────────────────────
# Test cases — each maps to an expected tool usage pattern
# judges will want to see all 3 patterns working
# ─────────────────────────────────────────────────────────────────
TEST_CASES = [
    {
        "id": "TC-01",
        "category": "RAG only",
        "query": "What does 3GPP specify about PDSCH scheduling in 5G NR?",
        "expected_tool": "rag_retrieve",
        "must_contain": ["PDSCH", "scheduling"]
    },
    {
        "id": "TC-02",
        "category": "RAG only",
        "query": "Explain the O-RAN Non-RT RIC A1 interface and its role in policy management.",
        "expected_tool": "rag_retrieve",
        "must_contain": ["A1", "Non-RT"]
    },
    {
        "id": "TC-03",
        "category": "Simulation only",
        "query": "Run a baseline simulation with 20 UEs on cell 0 and report the KPIs.",
        "expected_tool": "run_simulation",
        "must_contain": ["throughput", "latency"]
    },
    {
        "id": "TC-04",
        "category": "Simulation only",
        "query": "Run a high interference scenario with 30 UEs and tell me the SINR and packet loss.",
        "expected_tool": "run_simulation",
        "must_contain": ["SINR", "packet_loss"]
    },
    {
        "id": "TC-05",
        "category": "Both tools",
        "query": "Cell 7 is showing 40% throughput degradation. Run a simulation to diagnose and explain what the standards say about this condition.",
        "expected_tool": "both",
        "must_contain": ["throughput", "interference"]
    },
    {
        "id": "TC-06",
        "category": "Both tools",
        "query": "There are 45 handovers per minute on cell 3. Is this abnormal? Simulate handover stress and check what O-RAN recommends.",
        "expected_tool": "both",
        "must_contain": ["handover", "O-RAN"]
    },
    {
        "id": "TC-07",
        "category": "Both tools",
        "query": "Compare high_load and baseline scenarios for 50 UEs, and cite the 3GPP capacity planning guidelines.",
        "expected_tool": "both",
        "must_contain": ["baseline", "high_load"]
    },
]

# ─────────────────────────────────────────────────────────────────
# Core benchmark function
# ─────────────────────────────────────────────────────────────────
def run_single_query(query: str, thread_id: str, stream: bool = False) -> dict:
    """
    Sends one query to the agent and measures:
    - time_to_first_token (TTFT)
    - total_latency
    - response text
    - HTTP status
    """
    #payload = {
    #    "role": "user",
    #    "messages": query,
    #    "thread_id": thread_id,
    #    "stream": stream
    #}
    payload = {
    "query": query,
    "thread_id": thread_id,
    "stream": stream,
}

    result = {
        "query": query,
        "status_code": None,
        "total_latency_s": None,
        "ttft_s": None,
        "response": "",
        "error": None
    }

    try:
        t_start = time.perf_counter()

        if stream:
            first_token_recorded = False
            with requests.post(
                f"{GATEWAY_URL}/v1/chat",
                data=json.dumps(payload),
                stream=True,
                headers={"Content-Type": "application/json"},
                timeout=300
            ) as resp:
                result["status_code"] = resp.status_code
                for line in resp.iter_lines(decode_unicode=True):
                    if line.startswith("data: ") and line != "data: [DONE]":
                        if not first_token_recorded:
                            result["ttft_s"] = round(time.perf_counter() - t_start, 3)
                            first_token_recorded = True
                        result["response"] += line[6:]
        else:
            resp = requests.post(
                f"{GATEWAY_URL}/v1/chat",
                json=payload,
                timeout=300
            )
            result["status_code"] = resp.status_code
            result["response"] = resp.text

        result["total_latency_s"] = round(time.perf_counter() - t_start, 3)

    except requests.exceptions.ConnectionError as e:
        result["error"] = f"ConnectionError: {e}"
    except requests.exceptions.Timeout:
        result["error"] = "Timeout after 300s"

    return result


def check_quality(response: str, must_contain: list) -> dict:
    """Checks if required keywords appear in the response."""
    response_lower = response.lower()
    hits = {kw: kw.lower() in response_lower for kw in must_contain}
    score = sum(hits.values()) / len(hits) if hits else 0
    return {"keyword_hits": hits, "quality_score": round(score, 2)}


# ─────────────────────────────────────────────────────────────────
# Main benchmark runner
# ─────────────────────────────────────────────────────────────────
def run_benchmark(test_cases: list, runs_per_case: int = 3) -> dict:
    """
    Runs each test case `runs_per_case` times and aggregates:
    - mean latency
    - min / max latency
    - p95 latency
    - quality score
    - pass / fail
    """
    print(f"\n{'='*65}")
    print(f"  AINN-CoPilot Benchmark — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Gateway: {GATEWAY_URL}")
    print(f"  Cases: {len(test_cases)} | Runs per case: {runs_per_case}")
    print(f"{'='*65}\n")

    all_results = []

    for tc in test_cases:
        print(f"[{tc['id']}] {tc['category']} — {tc['query'][:60]}...")
        latencies = []
        ttfts = []
        quality_scores = []
        passed = True

        for run in range(runs_per_case):
            thread_id = str(uuid.uuid4())
            result = run_single_query(tc["query"], thread_id, stream=True)

            if result["error"]:
                print(f"  Run {run+1}: ERROR — {result['error']}")
                passed = False
                continue

            quality = check_quality(result["response"], tc["must_contain"])
            latencies.append(result["total_latency_s"])
            if result["ttft_s"]:
                ttfts.append(result["ttft_s"])
            quality_scores.append(quality["quality_score"])

            status = "✅" if quality["quality_score"] == 1.0 else "⚠️"
            print(
                f"  Run {run+1}: {status} "
                f"latency={result['total_latency_s']}s | "
                f"TTFT={result['ttft_s']}s | "
                f"quality={quality['quality_score']}"
            )

        if latencies:
            sorted_lat = sorted(latencies)
            p95_idx = max(0, int(len(sorted_lat) * 0.95) - 1)
            summary = {
                "id": tc["id"],
                "category": tc["category"],
                "expected_tool": tc["expected_tool"],
                "runs": runs_per_case,
                "mean_latency_s": round(statistics.mean(latencies), 3),
                "min_latency_s": round(min(latencies), 3),
                "max_latency_s": round(max(latencies), 3),
                "p95_latency_s": round(sorted_lat[p95_idx], 3),
                "mean_ttft_s": round(statistics.mean(ttfts), 3) if ttfts else None,
                "mean_quality": round(statistics.mean(quality_scores), 2),
                "passed": passed and statistics.mean(quality_scores) >= 0.5
            }
        else:
            summary = {
                "id": tc["id"],
                "category": tc["category"],
                "runs": runs_per_case,
                "passed": False,
                "error": "All runs failed"
            }

        all_results.append(summary)
        status_str = "PASS ✅" if summary.get("passed") else "FAIL ❌"
        print(f"  → {status_str} | mean={summary.get('mean_latency_s')}s | "
              f"quality={summary.get('mean_quality')}\n")

    # ── Aggregate report ──────────────────────────────────────────
    passed_count = sum(1 for r in all_results if r.get("passed"))
    all_latencies = [r["mean_latency_s"] for r in all_results if "mean_latency_s" in r]

    report = {
        "timestamp": datetime.now().isoformat(),
        "gateway_url": GATEWAY_URL,
        "total_cases": len(test_cases),
        "passed": passed_count,
        "failed": len(test_cases) - passed_count,
        "pass_rate": f"{round(passed_count / len(test_cases) * 100)}%",
        "overall_mean_latency_s": round(statistics.mean(all_latencies), 3) if all_latencies else None,
        "results": all_results
    }

    print(f"{'='*65}")
    print(f"  RESULT: {passed_count}/{len(test_cases)} passed ({report['pass_rate']})")
    print(f"  Mean latency across all cases: {report['overall_mean_latency_s']}s")
    print(f"{'='*65}\n")

    return report


# ─────────────────────────────────────────────────────────────────
# Save report to JSON
# ─────────────────────────────────────────────────────────────────
def save_report(report: dict):
    os.makedirs(os.path.join(os.path.dirname(__file__), "reports"), exist_ok=True)
    filename = os.path.join(
        os.path.dirname(__file__),
        "reports",
        f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"📄 Report saved to: {filename}")
    return filename


if __name__ == "__main__":
    report = run_benchmark(TEST_CASES, runs_per_case=3)
    save_report(report)
