# TelcoMind — Technical Report

**AI-Native Digital Twin Copilot with Intent-Driven Self-Healing**

## 1. Problem and Use-Case Relevance

Telecom operations require rapid correlation of network telemetry with standards, runbooks,
and prior incidents. This correlation is slow and error-prone when performed manually across
disconnected tools. TelcoMind addresses this by turning an operator's natural-language intent
(for example, "diagnose the bootstrap phase on this cell") into a grounded, citation-backed
diagnosis that combines curated knowledge with recorded simulation telemetry. The goal is to
reduce mean-time-to-understanding while remaining explicit and honest about what evidence was
used and what actions were — and were not — performed. The copilot diagnoses; it does not
execute real-network changes, which keeps the system safe to demonstrate and evaluate.

## 2. Architecture and Data Flow

TelcoMind is a **five-service** single-node system orchestrated with Docker Compose:

- **UI (Streamlit, :8501)** — operator entry point.
- **Gateway (:8888)** — public API; validates and proxies requests, attaches correlation IDs.
- **Agent (:9090)** — classifies operator intent and orchestrates tool calls.
- **RAG (:7001)** — retrieves grounding evidence from a curated quickstart knowledge base.
- **Simulation (:7000)** — serves recorded telemetry via deterministic replay.

Data flow: **User/UI → Gateway → Agent → {RAG, Simulation} → Agent → Gateway → User.**
The Agent queries the Simulation service for KPI evidence and the RAG service for
standards/runbook grounding, then returns a synthesized answer with citations and provenance.
Each response carries **replay provenance** (fixture id and mode) so the evidence source is
auditable rather than implied.

## 3. Main Technical Features

- **Recorded simulation replay** — the default Simulation mode replays a recorded fixture
  (`phase_bootstrap_normal`) with explicit provenance. Live Simu5G is optional and not part
  of the quickstart.
- **Lexical BM25 quickstart retrieval** — the default RAG profile is `quickstart` using
  `lexical_bm25`. Semantic/vector retrieval is optional and not the default.
- **Deterministic, citation-grounded synthesis** — answers are assembled deterministically
  from retrieved chunks with explicit citation IDs (`llm_used=false`). An optional
  OpenAI-compatible synthesis backend exists but is not used by default.
- **Meaningful end-to-end scenarios** — a runnable catalog drives the real Gateway and asserts
  structural correctness, provenance fields, expected retrieval, and forbidden claims.
- **Dependency-failure honesty** — unsupported replay faults and malformed requests return
  honest error statuses; a failure-injection mode stops and restarts dependencies to
  demonstrate graceful failure and recovery rather than fabricated output.
- **Correlation metadata** — Gateway and Agent propagate request/correlation identifiers for
  traceability across the scenario outputs.

## 4. Deployment and Evaluation

Deployment is a single command (`.\deploy.ps1`, `./deploy.sh`, or
`docker compose up -d --build`) that brings up all five services with health gating.

Verified evaluation evidence from this repository:

- **Five-service healthy** Compose deployment.
- **Successful host-side smoke test.**
- **Successful isolated offline test matrix** (Batch 9).
- **8/8 meaningful E2E scenarios** passing with grounded citations and replay provenance.
- **Successful failure injection and recovery.**
- Fixture and RAG corpus **checksums verified**; root and test Compose configurations render.
- Repository hygiene: **PASS=37, WARN=12, FAIL=0.**
- **~33-second cached development-machine deployment.**

The ~33s figure is **cached/warm development-machine evidence only**. It is **not** a
clean-machine guarantee and **not** a formal four-core constrained benchmark. The quickstart
requires **no GPU**.

## 5. Limitations and Advanced Modes

- Default simulation is **recorded replay**, not a live Simu5G execution during quickstart.
- **Full semantic/vector RAG** is optional and not the default.
- **vLLM / LLM synthesis** is optional and not used by default.
- No claim of **real telecom corrective action** — the system diagnoses only.
- No formal **clean-machine sub-ten-minute** installation proof and no formal **four-core**
  benchmark are asserted beyond available repository evidence.
- No **OPEA certification** is claimed.

Advanced modes (live Simu5G, semantic retrieval, GPU-accelerated LLM synthesis) are
supported as optional, environment-dependent configurations and are intentionally excluded
from the reproducible default quickstart to keep evaluation deterministic and honest.
