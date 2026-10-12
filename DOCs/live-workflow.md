# Live browser workflow

From the repository root:

```bash
./deploy.sh
```

Open http://localhost:8501 and submit:

> Run a baseline simulation with 10 UEs and diagnose throughput and latency with citations.

The UI submits a query job through the gateway. The Agent routes it to an isolated
Simu5G experiment, polls its progress, retrieves relevant RAG evidence, and calls
the configured synthesis backend. The browser shows progress, recorded samples
as they become available, final application KPIs and timeline, per-UE data,
citations, recommended action, and downloadable run artifacts.

The first build compiles OMNeT++ 6.3.0, INET 4.5.4 and Simu5G 1.4.4. This requires
CPU, memory, internet downloads and time; it does not require a GPU. Compiled
layers are reused on later starts. The deployment script updates its own running
project, so repeated deployment does not require killing unrelated processes.

## Modes and settings

- The default script combines `docker-compose.yml` with `docker-compose.live.yml`.
- `./deploy.sh --replay` selects the existing lightweight recorded demo.
- The live stack also accepts explicitly selected replay queries, with verified
  fixture provenance and visible parameter limitations.
- RAG defaults remain the curated lexical BM25 corpus and deterministic synthesis.
  This step does not enable full semantic ingestion or start vLLM automatically.
- Existing OpenAI-compatible synthesis configuration still flows to the RAG
  service. The UI reports the actual backend and any deterministic fallback.
- Deployment scripts prefer root `.env`, then fall back to `CODE/.env`, passing
  the selected file explicitly to Compose. Secrets need not be committed.
- The root Agent is the existing custom FastAPI orchestration service. Its jobs
  do not execute the separately configured `opea/agent` image.

In the sidebar, select Live or Replay. UE counts are extracted from the query
unless Override UE count is selected. Duration and seed apply to live runs.
Browser refresh can resume an active job through its `?job=...` URL.

The frontend supports native Light, Dark, and System appearance options from
the top-right main menu. Both themes cover inputs, charts, tables, and menus.
Resource comparisons overlay reference and candidate measurements on shared
axes. Scenario labels are readable names; API scenario identifiers are unchanged.

## Supported experiments

Live execution supports `baseline` / `normal_operation`, `traffic_burst`,
`resource_comparison`, and `mobility_handover`, with seven cells, downlink UDP
traffic, 1-200 UEs, 3-120 simulated seconds, and explicit seeds. Mobility uses
moving UEs and enabled NR handovers; the other scenarios use stationary UEs.
See [scenario controls and measurement limitations](live-scenarios.md).
Controlled fault injection, slicing, energy accounting, and automated remediation
remain unsupported; explicit requests for them are rejected.

Throughput is received application bytes per configured simulated traffic
interval. Delay is measured end-to-end application delay. Undelivered compares
sent and received application packets, including possible packets in flight;
it is not a direct radio loss measurement. Progressive charts show recorded
samples written so far and may lag the simulation because vectors are buffered.

## Job API

| Service | Endpoint | Purpose |
| --- | --- | --- |
| Gateway | `POST /v1/jobs` | Submit a query with `query`, optional `simulation` settings and `request_id`. |
| Gateway | `GET /v1/jobs/{id}` | Read status, stage, progress and final result. |
| Gateway | `DELETE /v1/jobs/{id}` | Request cancellation. |
| Gateway | `GET /v1/jobs/{id}/artifacts/{name}` | Download JSON, INI, scalar, vector or log evidence. |
| Simulation | `POST /jobs` | Submit a supported fresh experiment or paired resource comparison. |
| Simulation | `GET /jobs/{id}` | Read measured progress and results. |

Both job services have one worker and a bounded queue of eight active jobs.
Reusing a `request_id` with identical inputs returns the same job; changed inputs
return HTTP 409. Full queues return HTTP 429. Successful and failed job snapshots
are persisted atomically in named volumes. Interrupted jobs are marked failed
after service restart, rather than being reported as successful or rerun silently.
Artifacts are retained on disk; operators should monitor volume storage and
archive old runs as needed. `--down` preserves the named volumes.

## Verification

```bash
./deploy.sh --verify
```

The live smoke test executes a browser-equivalent query, checks a fresh run ID,
applied parameters and measured timeline, citations, duplicate protection,
artifact download, standards-only routing, and UI health. It is deployment
verification; normal operators submit their queries entirely through the UI.

Windows uses `.\deploy.ps1`, with `-Verify`, `-Status`, `-Logs`, `-Down`, or `-Replay`.
The PowerShell path requires separate verification on a Windows host.

## Validation recorded

Validated on Linux with Docker Desktop on 2026-10-13:

- All eight required isolated test suites passed: 209 tests, zero failures.
- `./deploy.sh` started the live stack and its gateway smoke check passed.
- A fresh 10-UE experiment recorded 8 Mbps, approximately 5 ms application delay,
  and 8500 sent/received packets, with a new engine run ID and downloadable evidence.
- Desktop and mobile browser checks passed for query submission, progress,
  measured charts, source display, standards-only routing and horizontal overflow.
- Browser refresh retained the active job ID. Cancelling the query also cancelled
  the child simulation job. Explicit replay selection completed successfully.
- Live synthesis was tested with the existing deterministic backend and lexical
  BM25 corpus. OpenAI-compatible policies were tested with mocked endpoints in
  the offline matrix; this validation did not call a real LLM provider.
- The recorded replay artifacts were restored to the CRLF bytes expected by
  their existing manifest. Their original SHA-256 values now match, and Git
  treats those artifacts as binary to preserve exact bytes across checkouts.

These are functional verification results, not formal performance measurements.
