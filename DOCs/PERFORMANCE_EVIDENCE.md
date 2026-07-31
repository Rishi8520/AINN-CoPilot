# Performance and Submission Evidence

**Generated:** 2026-08-01 (UTC)
**Git commit (before final submission commit):** `6075f14cfa3b1cbd707ee42e99de68859722e1d5`

## Environment (development machine, immediately available)

- **Docker:** version 29.5.2 (build 79eb04c)
- **Docker Compose:** v5.1.4
- **Host CPU:** Intel(R) Core(TM) Ultra 9 275HX — 24 cores / 24 logical processors
- **Host memory:** ~31.4 GB total physical

> This is the development/evaluation host. It is **not** a formally constrained four-core
> reference environment.

## Verified Results

- **Five-service health:** Simulation (7000), RAG (7001), Agent (9090), Gateway (8888), and
  UI (8501) all reported healthy during Batch 9 validation.
- **Cached deployment timing:** approximately **33 seconds** on the cached/warm development
  machine.
- **Smoke test:** passed (host-side smoke test against the running stack).
- **E2E scenarios:** **8/8** meaningful scenarios passed with grounded citations and replay
  provenance.
- **Failure paths:** unsupported replay fault returned the expected error status; malformed
  request returned the expected validation error status.
- **Failure injection and recovery:** dependency stop/restart demonstrated honest failure and
  successful recovery; a post-recovery supported scenario passed.
- **Integrity:** Simulation replay fixture manifest checksums and RAG quickstart corpus
  checksum verified. Root and test Compose configurations rendered successfully.
- **Repository hygiene:** PASS=37, WARN=12, FAIL=0.

## Evidence Classification (explicit)

| Evidence class | Status |
| --- | --- |
| **Cached / warm development evidence** | Established (~33s cached deployment, healthy stack, smoke + E2E pass) |
| **Clean / cold deployment evidence** | **Not formally established** (no cold rebuild timing captured) |
| **Formal four-core constrained evidence** | **Not formally established** (no constrained benchmark run) |

## Notes

- No universal performance guarantee is made. Timings depend on host hardware, Docker cache
  state, and image availability.
- The quickstart uses recorded replay, lexical BM25 retrieval, and deterministic synthesis
  (`llm_used=false`); **no GPU is required**.
- No cold rebuild or destructive cache clearing was performed to produce this evidence.
