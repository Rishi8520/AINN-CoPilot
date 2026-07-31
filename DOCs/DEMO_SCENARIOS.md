# Demo Scenarios

Batch 9 adds tracked, reproducible end-to-end demo scenarios that run through the real Gateway (`/v1/chat`) and validate Gateway -> Agent -> Simulation/RAG behavior.

## Scope and Truthfulness

- Replay is recorded output from `phase_bootstrap_normal`, not a newly executed live Simu5G run.
- Deterministic synthesis is not an LLM.
- Lexical BM25 retrieval is not semantic/vector retrieval.

## Scenario Catalog

Scenario: `grounded_diagnosis`
- Purpose: supported diagnosis using replay KPIs plus grounded evidence.
- UI prompt: `Run a baseline replay simulation with 20 UEs and diagnose likely throughput and mobility risks with citations.`
- Gateway command:
```bash
curl -sS http://localhost:8888/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"Run a baseline replay simulation with 20 UEs and diagnose likely throughput and mobility risks with citations.","thread_id":"demo-grounded-diagnosis","stream":false}'
```
- Expected flow: Gateway -> Agent -> Simulation replay + RAG quickstart retrieval -> deterministic synthesis.
- Expected evidence: structured `rag.sources[]` and `synthesis.citations[]`; replay provenance with `fixture_id=phase_bootstrap_normal`.
- Expected backend labels: `simulation.mode=replay`, `rag.rag_profile=quickstart`, `rag.retrieval_backend=lexical_bm25`, `synthesis.synthesis_backend=deterministic`, `synthesis.llm_used=false`.
- Prohibited interpretation: do not claim live Simu5G, semantic retrieval, GPU inference, or LLM output.

Scenario: `standards_question`
- Purpose: standards/specification grounding.
- UI prompt: `What do 3GPP and O-RAN references say about handover failure signaling and measurement handling?`
- Expected evidence: `source_type=spec` and allowlisted standards chunks where available.
- Prohibited interpretation: do not treat lexical ranking as confidence/probability.

Scenario: `runbook_kpi_question`
- Purpose: runbook guidance tied to replay KPI context.
- UI prompt: `Explain replay KPI implications for interference and load balancing using runbook guidance.`
- Expected evidence: `source_type=runbook`; KPI context from replay payload or explicit caller input.
- Prohibited interpretation: no fabricated KPI values.

Scenario: `scenario_mapping_question`
- Purpose: scenario/fault mapping evidence.
- UI prompt: `Map likely causes for handover-failure symptoms using scenario-mapping evidence and cite sources.`
- Expected evidence: `source_type=scenario` or runbook support.
- Prohibited interpretation: do not claim a fault simulation was executed.

Scenario: `out_of_scope_no_match`
- Purpose: honest insufficient-evidence behavior.
- UI prompt: `Provide 5G guidance for submarine quantum repeater maintenance procedures in deep ocean cables.`
- Expected evidence: empty or weak retrieval is acceptable if represented honestly.
- Prohibited interpretation: no invented citations.

Scenario: `unsupported_replay_fault`
- Purpose: unsupported replay-fault honesty.
- UI prompt: `Simulate handover_failure replay mode and return fault KPIs with citations.`
- Expected behavior: visible non-success (expected HTTP 502 via Gateway) because replay supports baseline aliases only.
- Prohibited interpretation: no healthy baseline KPI payload presented as requested fault execution.

Scenario: `malformed_request`
- Purpose: request validation contract.
- Gateway command:
```bash
curl -sS http://localhost:8888/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"thread_id":"demo-malformed","stream":false}'
```
- Expected behavior: HTTP 422 with validation details.

Scenario: `deterministic_repeatability`
- Purpose: repeatability of structural metadata (not prose).
- UI prompt: `Run baseline replay and summarize likely handover causes with citations.`
- Expected checks: stable fixture ID, profile/backend labels, citation/source identities across two runs.

## Runner Commands

```bash
python scripts/run_demo_scenarios.py --list
python scripts/run_demo_scenarios.py
python scripts/run_demo_scenarios.py --scenario grounded_diagnosis
python scripts/run_demo_scenarios.py --scenario deterministic_repeatability
python scripts/run_demo_scenarios.py --with-failure-injection
python scripts/run_demo_scenarios.py --json-only
python scripts/run_demo_scenarios.py --verbose
```

Outputs (ignored by Git):
- `e2e-results/summary.json`
- `e2e-results/summary.md`
- `e2e-results/logs/<scenario-id>-runN.json`
- `e2e-results/logs/<scenario-id>-runN.log`

## 2-3 Minute Demo Sequence

1. Show health: `docker compose ps` and `curl http://localhost:8888/v1/health`.
2. Run one grounded scenario from UI or API (`grounded_diagnosis`).
3. Show citations in `rag.sources` and `synthesis.citations`.
4. Show replay provenance fields under `simulation.result_reference.provenance`.
5. Run `unsupported_replay_fault` to show honest non-success.
6. Optionally run `--with-failure-injection` and show restored healthy services.

## Fallback API Procedure

If UI interaction fails, use Gateway directly:

```bash
curl -sS http://localhost:8888/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"query":"Run a baseline replay simulation with 20 UEs and diagnose likely throughput and mobility risks with citations.","thread_id":"fallback-api","stream":false}'
```

## How To Demonstrate Key Contracts

- Health: `GET /v1/health` and `GET /v1/agent/status` via Gateway.
- Citations: inspect `rag.sources[]` and `synthesis.citations[]`.
- Replay provenance: inspect `simulation.result_reference.mode_label`, `live_simulation`, and `provenance.fixture_id`.
- Dependency-failure honesty: run `python scripts/run_demo_scenarios.py --with-failure-injection`.
- Restore/reset stack: `docker compose down` then `./deploy.sh` or `.\deploy.ps1`.
