# Submission Gap Ledger

## Batch 8 Update - Root Test Matrix

- Added `tests/test_matrix.json`, `scripts/run_test_matrix.py`, `test.ps1`, and `test.sh` for isolated offline/static test execution with JUnit, logs, and JSON/text summaries under ignored `test-results/`.
- Added a Docker fallback test image (`Dockerfile.test`, `requirements.test.txt`, `docker-compose.test.yml`) that runs offline suites without GPU/model downloads and with execution-time networking disabled.
- Added Agent/Gateway/UI, matrix isolation, artifact integrity, static configuration, and hygiene-backed tests.
- Documented the package collision between `CODE/RAG/app` and `CODE/Simulation/app`; the matrix runs collision-prone suites in separate subprocesses.
- Offline tests still do not prove live Simu5G, full semantic RAG ingestion, real vLLM, external APIs, GPU behavior, or clean-machine timing.

## Batch 7 Update - Root Quickstart Deployment

- Added root `docker-compose.yml` for the CPU-safe single-node quickstart stack.
- Added `deploy.sh`, `deploy.ps1`, and `scripts/smoke_test.py` for one-click deploy, status, logs, down, and verification flows.
- Added quickstart Dockerfiles and requirements for Simulation replay, RAG lexical quickstart, Agent/Gateway, and UI.
- Default stack remains GPU-free, Tailscale-free, vLLM-free, Chroma-free, full-ingestion-free, live-Simu5G-free, and deterministic for synthesis.
- Root README, LICENSE, final report, formal under-10-minute timing, full RAG, live Simu5G, and optional vLLM runtime validation remain deferred.

## A. Executive summary

AINN-CoPilot / TelcoMind has substantial implementation across Agent, Gateway, UI, RAG, and Simulation components, including Docker assets, tests, knowledge-base material, and a full Simu5G source tree. It is not yet proven submission-ready.

This ledger does not claim compliance with the under-10-minute installation and first-run rule. It also does not claim clean-machine success because no clean-machine deployment test was run in Batch 1.

## B. Exact submission checklist

| Requirement | Status | Evidence |
| --- | --- | --- |
| Complete runnable source | PARTIAL | Source exists under `CODE/Agent`, `CODE/RAG`, and `CODE/Simulation`; runnable end-to-end state is not yet verified. |
| One-click deployment | MISSING | No root `docker-compose.yml` or `deploy.sh` found. Subproject compose files exist. |
| Root README | MISSING | No root `README.md` found. |
| Root LICENSE | MISSING | No root `LICENSE` found; `CODE/Simulation/simu5g/LICENSE.md` exists only for the vendored Simu5G tree. |
| Two-page technical report | MISSING | No root `TECHNICAL_REPORT.pdf` found. |
| Optional demo video | NOT YET VERIFIED | No root README/report exists to link a demo video. |
| Single-node deployment | NOT YET VERIFIED | Subproject compose files exist, but root single-node orchestration is absent. |
| CPU/no-GPU quickstart | PARTIAL | Batch 5 quickstart plus Batch 6 deterministic synthesis make RAG startup and synthesis CPU-safe by default; root one-click deployment and clean-machine timing remain unverified. |
| Under-10-minute installation and first run | NOT YET VERIFIED | No timing validation was run. |
| End-to-end UI/Gateway/Agent/Simulation/RAG/LLM workflow | NOT YET VERIFIED | Components exist, but no end-to-end smoke test was run. |
| Performance logs/screenshots | MISSING | No root submission evidence bundle was found. |
| Clean repository/archive | PARTIAL | Ignore rules were strengthened, but large tracked Simulation generated/results artifacts remain for Batch 2. |

## C. Repository evidence

### Existing services/components

- Agent and Gateway: `CODE/Agent/agent.py`, `CODE/Agent/gateway.py`, `CODE/Agent/tools/tools.py`.
- UI: `CODE/Agent/ui/app.py`.
- RAG service: `CODE/RAG/app/rag_service.py`, `CODE/RAG/app/vector_store.py`, `CODE/RAG/app/synthesis.py`.
- Simulation API and runner: `CODE/Simulation/app/main.py`, `CODE/Simulation/app/api/routes.py`, `CODE/Simulation/app/simulator`.
- Vendored simulation source: `CODE/Simulation/simu5g`.

### Existing tests

- RAG tests: `CODE/RAG/tests/test_contracts.py`.
- Agent evaluation assets: `CODE/Agent/eval/benchmark.py`, `CODE/Agent/eval/test_cases.json`.
- Simu5G fingerprint tests are present in `CODE/Simulation/simu5g/tests/fingerprint`.

### Docker/Compose files

- `CODE/Agent/Dockerfile.gateway`
- `CODE/Agent/ui/Dockerfile`
- `CODE/Agent/docker-compose.yml`
- `CODE/RAG/Dockerfile.rag`
- `CODE/RAG/docker-compose.yml`
- `CODE/Simulation/Dockerfile`
- `CODE/Simulation/docker-compose.yml`

No root compose file was found.

### Environment examples

- `CODE/.env.example` is tracked.
- No tracked `.env` file was found.
- A local `CODE/.venv` directory exists in the working tree and should remain untracked.

### Large/runtime-generated artifacts

- `CODE/Simulation/app/scenarios/results`: 515 files, about 958.7 MiB, 515 tracked files.
- `CODE/Simulation/app/scenarios/generated`: 487 files, about 2.2 MiB, 487 tracked files.
- Batch 1 intentionally left both directories untouched for Batch 2 fixture preservation and cleanup.
- Batch 2 preserves the smallest complete real run found as a recorded replay/parser fixture at `CODE/Simulation/fixtures/replay/phase_bootstrap_normal`.
- Batch 2 final tracked runtime state is limited to README.md and `.gitkeep` files in the results/generated runtime directories: 4 files, 920 bytes total.
- Batch 2 final tracked fixture state is 6 files, 3,095,624 bytes total.

### Root deliverables

- Root `.gitignore` exists.
- Root `README.md`, `LICENSE`, `TECHNICAL_REPORT.pdf`, `docker-compose.yml`, and `deploy.sh` were not found.

### RAG data/index state

- RAG knowledge base PDFs and runbooks are tracked under `CODE/RAG/knowledge_base`.
- Local runtime vector storage exists at `CODE/RAG/storage/chroma`, about 143.6 MiB, not tracked.
- No prebuilt quickstart index strategy is documented at the root.

### Simulation build/runtime state

- Simulation API, Dockerfile, compose file, scenarios, and Simu5G source tree exist.
- `CODE/Simulation/simu5g.tar.gz` was a zero-byte tracked file and was removed as an invalid/disposable incomplete archive.
- Empty runtime file `CODE/Simulation/.cmdenv-log` was removed.

### Agent/Gateway/UI state

- Gateway exposes `/v1/health`, `/health`, `/v1/agent/status`, and `/v1/chat`.
- Batch 3 changes UI native-host default to `GATEWAY_BASE_URL=http://localhost:8888`.
- Batch 3 changes Agent/RAG vLLM configuration to prefer `VLLM_BASE_URL`; `LLM_ENDPOINT_URL` remains a compatibility alias.
- Batch 3 changes Agent tool defaults to Simulation `http://localhost:7000` and RAG `http://localhost:7001`.

### Conflicting or stale endpoint configuration discovered

- `CODE/Simulation/docker-compose.yml` runs Simulation on container port `7000`.
- `CODE/RAG/docker-compose.yml` runs RAG health on `7000` and maps optional vLLM `8080:8000`.
- Agent tool defaults use `8888` for Simulation and `8889` for RAG.
- Batch 3 removes the earlier Tailscale-oriented comments and error hints from `CODE/Agent/tools/tools.py`.

## D. Blocker categories

### Repository hygiene and size

The broader local working tree previously measured about 6.9 GiB when ignored local environments and caches were included. Batch 1's Windows-safe hygiene validator reported accessible non-cache local content separately from Git-tracked submission content: about 1.1 GiB across 1,137 accessible files locally, and about 1008.0 MiB across 1,129 accessible tracked files.

Batch 2 removes the bulk tracked Simulation runtime outputs after preserving a traceable real fixture. The post-cleanup tracked submission content is about 49.4 MiB across 139 accessible tracked files. The targeted Simulation runtime directories now track only README.md and `.gitkeep`; the recorded fixture is reported separately at about 3.0 MiB.

### One-click deployment

No root `docker-compose.yml` or `deploy.sh` exists. Subproject compose files are not yet unified into a single submission quickstart.

### Port and network configuration

Batch 3 resolves the previously detected defaults disagreement. Canonical host ports are Simulation `7000`, RAG `7001`, vLLM/OpenAI-compatible API `8080`, Gateway `8888`, Agent `9090`, and UI `8501`. Subproject compose files and env examples are aligned to those values. The root one-click compose is still deferred to Batch 7.

### API-contract alignment

Gateway, Agent, RAG, and Simulation endpoints exist, but no end-to-end contract smoke test was run in Batch 1.

### Tailscale assumptions

Batch 3 removes active/default Tailscale-oriented Agent tool comments and error hints. Tailscale may remain in historical ledger notes as prior-development context, but active runtime defaults and examples must not require Tailscale or 100.x teammate-machine URLs.

### RAG fresh-clone/index readiness

Knowledge-base files exist, and Batch 5 adds a committed quickstart corpus under `CODE/RAG/quickstart` for offline lexical retrieval. Local Chroma runtime storage remains untracked. Full semantic RAG fresh-clone readiness is not proven without explicit full ingestion or a supplied existing index.

### Full RAG-ingestion duration

No full ingestion was run. The default quickstart must avoid full PDF ingestion and keep full-corpus ingestion as an optional rebuild.

### CPU/no-GPU synthesis

Batch 6 makes deterministic synthesis the RAG default. It requires no GPU, model download, external service, API key, or network call. Optional OpenAI-compatible/vLLM synthesis is explicit and truthfully labelled.

### vLLM/GPU optional mode

vLLM remains an optional OpenAI-compatible implementation on port `8080`, not a default startup requirement. Batch 6 documents the development-tested NVIDIA NGC image/model path but does not pull, run, or validate it.

### Simulation quickstart versus real Simu5G mode

The repository includes real Simu5G assets. Batch 2 removed bulk tracked runtime outputs and retained `phase_bootstrap_normal` as a recorded replay/parser fixture. Batch 4 separates CPU-safe recorded replay mode from live Simu5G mode and labels replay results as recorded/replayed.

### Truthful Simulation health/readiness

Batch 4 separates Simulation liveness from readiness. `/health` reports FastAPI process liveness only. `/ready` reports replay readiness, live readiness, configured default-mode readiness, fixture validation status, and missing live prerequisites.

### Test coverage

Some tests and evaluation assets exist, but full service and end-to-end smoke coverage is not established.

### Performance evidence

No root performance log or screenshot evidence package was found.

### Documentation

Root README and operator quickstart documentation are missing.

### License

Root license is missing.

### Technical report

Two-page technical report is missing.

### Video/demo materials

No root-linked demo video evidence was found.

### EvalAI frozen submission packaging

No tagged commit/archive workflow is documented. The final uploaded EvalAI archive is a static snapshot and should correspond to a tagged Git commit.

## E. Important architectural principles for remediation

- Tailscale must not be required for single-node submission.
- Default quickstart must not perform full PDF ingestion.
- Default quickstart must not require GPU/vLLM.
- Full-corpus ingestion should remain available as an optional rebuild.
- GPU vLLM should remain available as an optional enhanced profile.
- Generated simulation outputs should not dominate the Git repository.
- Any quickstart/replay fixtures must be small, traceable, and clearly labelled.
- Health endpoints must not report success when critical runtime dependencies have failed.
- The final uploaded EvalAI archive is a static snapshot and should correspond to a tagged Git commit.

## F. Batch 3 evidence

Batch 3 canonical ports:

| Service | Host port | Canonical base URL env |
| --- | ---: | --- |
| Simulation | 7000 | `SIMULATION_BASE_URL` |
| RAG | 7001 | `RAG_BASE_URL` |
| vLLM/OpenAI-compatible API | 8080 | `VLLM_BASE_URL` |
| Gateway | 8888 | `GATEWAY_BASE_URL` |
| Agent | 9090 | `AGENT_BASE_URL` |
| UI | 8501 | `UI_PORT` |

Batch 3 API mismatches fixed:

- Agent Simulation calls now send JSON to `POST /simulate` with `scenario`, `ue_count`, `cell_id`, `slice_type`, and `mode`.
- Simulation `POST /simulate` now has a Pydantic JSON request model, validates malformed inputs, and reports requested/applied/unsupported parameters instead of silently discarding Agent metadata.
- Agent RAG calls now use structured `POST /v1/retrievaltool/json`; the text endpoint remains as a compatibility route.
- RAG/vLLM configuration now prefers `VLLM_BASE_URL` and still reads `LLM_ENDPOINT_URL` as a compatibility alias.
- Gateway and UI defaults no longer collide with vLLM's `8080` host port.

Batch 3 Tailscale status:

- Active/default runtime configuration no longer requires Tailscale or 100.x teammate-machine URLs.
- Historical ledger/documentation may still mention prior Tailscale use, but those references are not active defaults.

Batch 3 validation evidence, updated by Batch 3A:

- The actual lightweight pytest suites ran through WSL using the existing Linux project environment at `CODE/.venv/bin/python`.
- Required Batch 3A pytest command covered Agent, Simulation API, Simulation replay fixture, RAG, and cross-service contract tests: `55 passed`, `0 failed`, `0 skipped`, `12 warnings`.
- `compileall` over modified Python packages/tests/scripts passed using the same WSL project environment.
- `contracts/services.json` parsed successfully and reports unique host ports: `7000`, `7001`, `8080`, `8501`, `8888`, `9090`.
- `scripts/check_repo_hygiene.py` passed with `SUMMARY PASS=21 WARN=12 FAIL=0`.
- `git diff --check` passed.
- No packages were installed; WSL access to the existing project environment was used. No Docker, Simu5G, RAG ingestion, vLLM, or model download was run.

## G. Batch 4 evidence

Batch 4 Simulation mode behavior:

- `POST /simulate` now dispatches explicitly to `replay` or `live`.
- Default quickstart-oriented Simulation mode is CPU-safe `replay`.
- Replay mode uses only the approved `phase_bootstrap_normal` fixture and the production `KPIParser.parse_sca_file`.
- Replay validates the fixture manifest, file existence, file sizes, and SHA-256 checksums when strict validation is enabled.
- Replay responses are labelled `recorded_replay`, set `live_simulation: false`, and include fixture provenance without absolute machine paths.
- Unsupported replay scenarios such as fault, degraded, handover-failure, outage, and unknown scenarios do not receive the healthy fixture.
- Requested `ue_count`, `cell_id`, `slice_type`, and `seed` are preserved under requested parameters but are not falsely listed as applied for replay.
- Live mode checks `SIMULATION_LIVE_ENABLED`, `opp_run`, configured CWD, INET/Simu5G libraries, NED path entries, scenario assets, writable runtime directories, and runner availability without starting a simulation.
- Live mode does not silently fall back to replay when disabled, unavailable, failed, or empty.
- Stale live metrics cannot make a stopped or failed live runner report `completed`.
- `/health`, `/ready`, and `/capabilities` distinguish liveness from replay/live readiness.

Batch 4 limitations still open:

- Live Simu5G execution is still not proven on this checkout.
- Replay is not evidence of current live OMNeT++/Simu5G execution.
- Replay is not evidence of fault/degraded behavior, live `.vec` polling, Docker startup, or dynamic application of arbitrary request parameters.
- Root one-click deployment remains Batch 7.
- Under-10-minute performance proof remains Batch 10.

Batch 4 validation evidence:

- Offline Simulation tests cover replay, live unavailable/failure behavior with mocks, health/readiness, query compatibility, JSON precedence, and fixture integrity.
- No Docker container was started; only `docker compose -f CODE/Simulation/docker-compose.yml config` is intended for Compose validation.
- No packages, models, OMNeT++, INET, Simu5G, or external assets were downloaded.

## G2. Batch 5 evidence

Batch 5 RAG quickstart profile:

- `RAG_PROFILE` now accepts exactly `quickstart` and `full`; empty defaults to `quickstart` and invalid values fail clearly.
- Quickstart is the default submission-oriented profile and uses deterministic lexical BM25-style ranking over `CODE/RAG/quickstart/corpus.jsonl`.
- Quickstart does not initialize Chroma, sentence-transformers, BGE embedding models, rerankers, CUDA, vLLM, external embedding/reranking services, model downloads, full PDF ingestion, or runtime index writes during startup.
- The committed quickstart corpus contains 10 chunks and is 13,623 bytes. It is derived from existing runbooks, scenario mapping, and selected PDF pages already present under `CODE/RAG/knowledge_base`.
- `CODE/RAG/quickstart/manifest.json` records source-relative paths, source SHA-256 hashes, source sizes, extraction methods, corpus hash, corpus id, version, and chunk count. Each JSONL chunk records a stable id, source metadata, source hash, and chunk-text hash.
- `scripts/build_quickstart_corpus.py --verify` validates deterministic generated output without rewriting. `scripts/evaluate_quickstart.py` runs offline demo queries and reports returned chunk ids, source types, rank positions, profile/backend, and latency.
- Retrieval responses now identify `rag_profile`, `retrieval_backend`, `corpus_id` or `index_id`, `result_count`, `fallback_used`, and `warnings`. Lexical scores are labelled `bm25_raw` ranking scores, not confidence or probability.
- `/health` is liveness only. `/ready` reports configured-profile readiness. `/capabilities` reports supported profiles/backends and synthesis capability.
- Deterministic synthesis now reports `synthesis_backend=deterministic` and `llm_used=false`; successful vLLM synthesis reports `synthesis_backend=vllm` and `llm_used=true`; vLLM failure with deterministic fallback sets `fallback_used=true` and emits a warning.
- Full semantic RAG remains explicit via `RAG_PROFILE=full`, preserves the Chroma/BGE/reranker pipeline, and reports unavailable when dependencies or a non-empty index are absent. It does not fall back to quickstart.
- `RAG_AUTO_INGEST=false` is the documented default, and normal service startup does not ingest the full corpus.

Batch 5 limitations still open:

- Full semantic ingestion and full Chroma rebuild were intentionally not run.
- Full-profile clean-machine execution is not proven.
- Quickstart lexical retrieval does not prove semantic retrieval quality.
- No model download occurred during quickstart validation.
- No formal under-10-minute or four-core timing claim is made; that remains Batch 10.
- Root one-click deployment remains Batch 7.

## G3. Batch 6 evidence

Batch 6 synthesis and optional LLM behavior:

- `RAG_SYNTHESIS_BACKEND` accepts exactly `deterministic` and `openai_compatible`; empty defaults to `deterministic` and invalid values fail configuration.
- Deterministic synthesis is the submission default and reports `requested_backend=deterministic`, `synthesis_backend=deterministic`, `llm_used=false`, and `fallback_used=false`.
- Deterministic mode does not instantiate the LLM client and performs no HTTP request.
- `LLM_BASE_URL` is canonical. `VLLM_BASE_URL` and `LLM_ENDPOINT_URL` are documented legacy aliases only when `LLM_BASE_URL` is absent or empty.
- Optional OpenAI-compatible synthesis uses `/v1/chat/completions`, `temperature=0`, bounded max tokens, explicit connect/read timeouts, optional Authorization only when `LLM_API_KEY` is set, and defensive response parsing.
- LLM success is reported only after a valid response. Optional failures fall back to deterministic synthesis only when policy permits. Required or fallback-disabled failures return structured failure metadata.
- Deterministic fallback is never labelled as LLM output, vLLM output, or successful optional LLM generation.
- Citation IDs are stable (`C1`, `C2`, ...), structured citation objects remain source-grounded, and unknown model citation IDs are flagged instead of remapped.
- Prompt-injection mitigation treats retrieved text as data, delimits evidence blocks, and tests a malicious evidence chunk requesting an invented citation. This is documented as a mitigation, not a guarantee.
- `/health` remains liveness only. `/ready` includes synthesis policy readiness/degraded status. `/capabilities` reports configured synthesis backend and optional OpenAI-compatible status without secrets or endpoint reachability claims.
- OPEA scope is interface-level: retrievaltool-compatible RAG endpoint, OpenAI-compatible LLM interface support, and external embedding/reranker interface compatibility. No formal OPEA certification or end-to-end OPEA deployment is claimed.

Batch 6 limitations still open:

- Optional vLLM runtime was not pulled, started, or tested in this batch.
- No external LLM endpoint, GPU, model download, Docker startup, full RAG ingestion, or Simu5G run was performed.
- Root one-click deployment remains Batch 7.
- Formal four-core timing remains Batch 10.

## H. Ordered 15-batch remediation plan

| Batch | Goal | Expected files/components | Acceptance gate | Risks |
| --- | --- | --- | --- | --- |
| 1. Repository hygiene and readiness ledger | Establish safe ignore rules, remove disposable tracked artifacts, and create this evidence ledger. | `.gitignore`, `CODE/.gitignore`, `SUBMISSION_GAP_LEDGER.md`, `scripts/check_repo_hygiene.py`. | Hygiene script passes with no Batch 1 FAIL findings. | Accidentally hiding required fixtures or overclaiming readiness. |
| 2. Simulation artifact cleanup and traceable fixtures | Completed in Batch 2: preserved the `phase_bootstrap_normal` recorded fixture, documented provenance/checksums, added parser fixture tests, and removed tracked bulk generated/results artifacts. | `CODE/Simulation/fixtures/replay/phase_bootstrap_normal`, `CODE/Simulation/app/scenarios/results`, `CODE/Simulation/app/scenarios/generated`, `CODE/Simulation/tests/test_replay_fixtures.py`, `scripts/check_repo_hygiene.py`. | Runtime directories track only README.md and `.gitkeep`; fixture manifest and checksums validate; production KPI parser reads the recorded `.sca`. | Fixture proves parser compatibility with one recorded healthy bootstrap run only; live Simu5G startup and degraded/fault replay remain later-batch work. |
| 3. Canonical ports, environment, and API contracts | Completed in Batch 3: established canonical single-node ports, env variables, Simulation/RAG/vLLM/Gateway/Agent/UI contracts, and active Tailscale removal. | `.env.example`, `CODE/.env.example`, `contracts/services.json`, `DOCs/SERVICE_CONTRACTS.md`, Agent/Gateway/UI/RAG/Simulation config and contract tests, `scripts/check_repo_hygiene.py`. | Offline contract tests and hygiene checks validate unique canonical ports, configurable URLs, JSON Simulation calls, structured RAG retrieval, vLLM path construction, and no active/default Tailscale dependency. | Root one-click deployment is still deferred to Batch 7; Simulation truthful replay/live dual-mode behavior remains Batch 4. |
| 4. Simulation dual-mode design | Completed in Batch 4: separated quickstart replay/fixture mode from live Simu5G execution. | Simulation config, fixture loader, readiness probes, API dispatch, docs/tests. | CPU-safe replay works without Simu5G; live mode reports structured unavailable/failure unless explicitly enabled and ready. | Full live Simu5G execution is still unproven on this checkout. |
| 5. RAG quickstart/prebuilt-index strategy | Completed in Batch 5: added default offline quickstart corpus/profile while preserving explicit full semantic mode. | `CODE/RAG/quickstart`, RAG profile config, lexical retriever, readiness/capabilities, docs/tests/hygiene. | Quickstart corpus verifies offline, demo queries retrieve evidence, API metadata identifies profile/backend, full mode never silently falls back. | Full semantic rebuild, clean-machine full execution, one-click deployment, and formal timing remain later-batch risks. |
| 6. CPU/no-GPU LLM and OPEA fallback strategy | Completed in Batch 6: deterministic synthesis is the default, optional OpenAI-compatible/vLLM is explicit, fallback semantics are tested, and OPEA claims are interface-scoped. | RAG config/client/policy/schema/readiness/capabilities, env examples, docs/tests/hygiene. | Offline RAG tests validate deterministic no-network synthesis, mocked OpenAI-compatible success/failure, citation validation, and readiness/capabilities semantics. | Optional vLLM runtime and end-to-end OPEA deployment remain unverified. |
| 7. Root one-click Compose/deploy script | Add root deployment entry point. | `docker-compose.yml`, `deploy.sh`, root `.env.example`. | One documented command starts the submission stack. | Port conflicts, slow image builds, missing health checks. |
| 8. Automated tests | Add focused unit and contract tests for critical interfaces. | Tests under component test folders and root smoke helpers. | Lightweight tests pass without Docker/model startup. | Tests becoming coupled to unavailable services. |
| 9. End-to-end smoke test | Add single-node smoke path across UI/Gateway/Agent/RAG/Simulation/LLM. | Smoke script and expected outputs. | Smoke test validates a cited response and simulation KPI path. | Flaky startup timing and health checks. |
| 10. Four-core performance validation and optimization | Measure and tune install/demo under competition constraints. | Benchmark logs, timing scripts, optimization notes. | Evidence shows first run within target hardware assumptions. | Hardware variability and model download time. |
| 11. CI and optional prebuilt image publishing | Add CI checks and optionally publish images for faster setup. | GitHub Actions, image docs, tags. | CI validates hygiene, tests, and smoke where feasible. | CI secrets or registry setup complexity. |
| 12. Root README and operator documentation | Write complete root operator docs. | `README.md`, architecture diagrams or links. | README includes overview, setup, requirements, outcomes, commands, endpoints/URLs. | Docs drifting from actual commands. |
| 13. License and two-page technical report | Add compliant license and concise report. | `LICENSE`, `TECHNICAL_REPORT.pdf`. | License is Apache 2.0 or MIT; report is no more than two pages. | Third-party license obligations need review. |
| 14. UI/demo/video package | Prepare demo flow and optional video. | Demo script, screenshots, video link in docs. | 1-3 minute demo demonstrates core workflow truthfully. | Demo depending on local-only state. |
| 15. Clean-room submission audit and tagged archive | Validate a fresh clone and produce final static archive. | Tag, release/archive notes, final audit log. | Clean-machine run passes; EvalAI archive matches tagged commit. | Last-minute generated files or missing large assets. |
