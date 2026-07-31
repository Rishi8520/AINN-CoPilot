# Service Contracts

Batch 3 establishes a single-node service contract for AINN-CoPilot / TelcoMind. Tailscale is not required for submission operation. Native host execution may use `localhost`; Docker/container execution must use service DNS names on a shared Docker network created later in Batch 7.

## Canonical Services

| Service | Host port | Container port | Native host URL | Future Docker URL | Health |
| --- | ---: | ---: | --- | --- | --- |
| Simulation API | 7000 | 7000 | `http://localhost:7000` | `http://simulation:7000` | `/health` liveness, `/ready` readiness |
| RAG API | 7001 | 7001 | `http://localhost:7001` | `http://rag:7001` | `/health` liveness, `/ready` readiness |
| vLLM/OpenAI API | 8080 | 8000 | `http://localhost:8080` | `http://vllm:8080` | image-dependent `/health` |
| Gateway API | 8888 | 8888 | `http://localhost:8888` | `http://gateway:8888` | `/v1/health`, `/health` |
| Agent API | 9090 | 9090 | `http://localhost:9090` | `http://agent:9090` | `/v1/health_check` |
| UI/Streamlit | 8501 | 8501 | `http://localhost:8501` | `http://ui:8501` | `/healthz` |

`localhost` from a browser means the user's machine. `localhost` from a container means that same container, not another service. Use Docker DNS names such as `http://rag:7001` only inside the future shared Docker network.

## Environment Variables

| Variable | Purpose | Docker default | Native-host equivalent |
| --- | --- | --- | --- |
| `SIMULATION_BASE_URL` | Simulation API base URL | `http://simulation:7000` | `http://localhost:7000` |
| `RAG_BASE_URL` | RAG API base URL | `http://rag:7001` | `http://localhost:7001` |
| `VLLM_BASE_URL` | OpenAI-compatible vLLM base URL | `http://vllm:8080` | `http://localhost:8080` |
| `GATEWAY_BASE_URL` | Gateway API base URL | `http://gateway:8888` | `http://localhost:8888` |
| `AGENT_BASE_URL` | Agent API base URL | `http://agent:9090` | `http://localhost:9090` |
| `SIMULATION_PORT` | Simulation host port | `7000` | `7000` |
| `SIMULATION_DEFAULT_MODE` | Simulation mode used when request mode is omitted | `replay` | `replay` |
| `SIMULATION_REPLAY_FIXTURE` | Approved recorded replay fixture id | `phase_bootstrap_normal` | `phase_bootstrap_normal` |
| `SIMULATION_REPLAY_STRICT_CHECKSUMS` | Verify replay fixture SHA-256 checksums | `true` | `true` |
| `SIMULATION_LIVE_ENABLED` | Enable real Simu5G/OMNeT++ live execution path | `false` | `false` |
| `RAG_PORT` | RAG host port | `7001` | `7001` |
| `RAG_PROFILE` | RAG profile, exactly `quickstart` or `full` | `quickstart` | `quickstart` |
| `RAG_QUICKSTART_CORPUS_PATH` | Quickstart JSONL corpus path, resolved from `CODE/RAG` when relative | `quickstart/corpus.jsonl` | `quickstart/corpus.jsonl` |
| `RAG_QUICKSTART_TOP_K` | Quickstart default retrieval count | `5` | `5` |
| `RAG_FULL_INDEX_PATH` | Existing Chroma path for full semantic mode | `/data/chroma` | `CODE/RAG/storage/chroma` |
| `RAG_AUTO_INGEST` | Whether service startup may ingest the full corpus | `false` | `false` |
| `RAG_STRICT_PROVENANCE` | Verify quickstart source and chunk SHA-256 hashes | `true` | `true` |
| `VLLM_PORT` | vLLM host port | `8080` | `8080` |
| `GATEWAY_PORT` | Gateway host port | `8888` | `8888` |
| `AGENT_PORT` | Agent host port | `9090` | `9090` |
| `UI_PORT` | Streamlit host port | `8501` | `8501` |

Compatibility aliases are still read where useful: `SIM_SERVICE_URL`, `RAG_SERVICE_URL`, `LLM_ENDPOINT_URL`, `AGENT_ENDPOINT`, and `GATEWAY_URL`.
For each alias pair, precedence is canonical variable, then legacy alias, then safe default. Empty or whitespace-only values are ignored and trailing slashes are normalized.

## Simulation API

Canonical endpoint: `POST /simulate`

Request:

```json
{
  "scenario": "baseline",
  "ue_count": 20,
  "cell_id": "cell-1",
  "slice_type": "eMBB",
  "seed": 42,
  "mode": "replay"
}
```

Replay response:

```json
{
  "run_id": "replay-phase_bootstrap_normal-generated-request-id",
  "status": "completed",
  "mode": "replay",
  "requested_parameters": {
    "scenario": "baseline",
    "ue_count": 20,
    "cell_id": "cell-1",
    "slice_type": "eMBB",
    "seed": null,
    "mode": "replay"
  },
  "applied_parameters": {
    "mode": "replay",
    "scenario_alias": "baseline",
    "fixture_id": "phase_bootstrap_normal",
    "scenario_fixture_mapping": {
      "baseline": "phase_bootstrap_normal"
    }
  },
  "unsupported_parameters": {
    "ue_count": "Replay uses a recorded fixture; requested ue_count does not alter recorded output.",
    "cell_id": "Replay uses a recorded fixture; requested cell_id is accepted only as metadata.",
    "slice_type": "Replay uses a recorded fixture; requested slice_type is accepted only as metadata.",
    "seed": "Replay uses a recorded fixture; requested seed does not alter recorded output."
  },
  "metrics": {
    "aggregate": {
      "throughput_mbps": 2.1548,
      "latency_ms": 2.0,
      "packet_loss_percent": 0.0
    }
  },
  "result_reference": {
    "mode_label": "recorded_replay",
    "live_simulation": false,
    "provenance": {
      "fixture_id": "phase_bootstrap_normal",
      "checksums_verified": true,
      "parser": "app.simulator.kpi_parser.KPIParser.parse_sca_file",
      "result_reference": "fixtures/replay/phase_bootstrap_normal/phase_bootstrap_normal.sca"
    }
  },
  "error": null
}
```

Statuses are `accepted`, `started`, `completed`, `failed`, `unsupported`, or `timeout`. The older query-parameter form remains available as a compatibility path, but JSON is canonical. If JSON and query parameters are both supplied, the JSON body is used. Unknown scenarios, invalid modes, and unsupported slice types are rejected with validation errors.

Replay mode supports only recorded healthy-bootstrap aliases: `baseline`, `normal`, `normal_operation`, `bootstrap_normal`, and `phase_bootstrap_normal`. Replay always labels output as recorded/replayed and sets `live_simulation: false`.

Live mode requires `SIMULATION_LIVE_ENABLED=true` and available Simu5G prerequisites. If live mode is disabled, unavailable, fails, or produces empty output, the API returns structured failure/unavailable details and does not substitute replay metrics. Live `completed` means a real runner phase succeeded and produced parsed aggregate metrics.

Simulation health paths:

- `GET /health`: process liveness only. It does not claim live Simu5G availability.
- `GET /ready`: structured readiness for replay, live, configured default mode, fixture validation, and missing live prerequisites. Returns `200` when the configured default mode can serve requests and `503` otherwise.
- `GET /capabilities`: structured mode capability output without readiness HTTP semantics.

## RAG API

RAG has two explicit profiles:

- `quickstart`: default CPU-safe offline profile using `CODE/RAG/quickstart/corpus.jsonl` and deterministic lexical BM25-style ranking. It does not initialize Chroma, BGE embeddings, rerankers, CUDA, vLLM, or full PDF ingestion at startup.
- `full`: advanced semantic profile using the existing Chroma/BGE/reranker pipeline. It requires an existing non-empty Chroma collection or explicit `/ingest` in full mode. It never receives quickstart fallback.

Canonical structured retrieval endpoint: `POST /v1/retrievaltool/json`

```json
{
  "text": "What causes handover failure in 5G NR?",
  "top_k": 4
}
```

The response is `RetrievalResponse` with `query`, `answer_context`, structured `sources`, `raw.result_count`, `rag_profile`, `retrieval_backend`, `corpus_id` or `index_id`, `result_count`, `fallback_used`, and `warnings`. Source citations preserve `source`, `title`, `section`, `chunk`, `page`, `kind`, `source_type`, `score_type`, and backend/profile metadata when available. Empty retrieval returns a valid response with an empty `sources` list; service failures are HTTP/client errors. Lexical BM25 scores are raw ranking scores, not confidence, probability, or semantic similarity.

Text compatibility endpoint: `POST /v1/retrievaltool`

Canonical synthesis endpoint: `POST /synthesize`

```json
{
  "query": "Summarize likely handover failure causes.",
  "top_k": 4,
  "simulation_kpis": {
    "handover_success_rate": 0.72
  },
  "intent_type": "DIAGNOSTIC"
}
```

Synthesis returns `answer`, `confidence`, structured `citations`, `assumptions`, `recommended_action`, `used_simulation_kpis`, `intent_type`, `retrieval_context_count`, `synthesis_backend`, `llm_used`, `fallback_used`, and `warnings`. If vLLM is disabled or unavailable, deterministic fallback is reported and is not labelled as vLLM output.

RAG health paths:

- `GET /health`: process liveness only. It reports the configured profile/backend but does not claim semantic index readiness.
- `GET /ready`: returns `200` when the configured profile is ready and `503` when unavailable. Quickstart readiness validates corpus and provenance. Full readiness checks dependencies and a usable non-empty collection without silently creating a successful quickstart response.
- `GET /capabilities`: reports supported profiles/backends, active profile, deterministic synthesis availability, and whether vLLM is configured, without exposing secrets or absolute local paths.

## vLLM API

Canonical endpoint: `POST /v1/chat/completions`

```json
{
  "model": "Qwen/Qwen2.5-7B-Instruct",
  "messages": [
    {"role": "user", "content": "Explain handover failure."}
  ],
  "temperature": 0.1,
  "max_tokens": 400
}
```

Local vLLM does not require a real API key unless an image or wrapper is configured to require one. GPU startup and model download are not part of Batch 3 validation.

## Gateway And Agent

Gateway entry point: `POST /v1/chat`

```json
{
  "query": "Run a normal operation simulation with 20 UEs and cite likely causes.",
  "thread_id": "demo-thread",
  "stream": false
}
```

Gateway forwards to Agent `POST /v1/chat/completions`. Health/status paths are `/v1/health`, `/health`, and `/v1/agent/status`. UI uses `GATEWAY_BASE_URL` or `GATEWAY_URL`; browser-local default is `http://localhost:8888`.

## Timeout And Error Behavior

Simulation tool calls use a 120 second timeout. RAG retrieval tool calls use a 30 second timeout. Gateway health probes and startup probes are environment-configurable. Client code must surface non-2xx, timeout, connection, and malformed JSON failures as errors rather than returning fake success.

## Compatibility And Deferred Work

Compatibility aliases retained: Simulation query parameters on `/simulate`, RAG text endpoint `/v1/retrievaltool`, and legacy env names listed above.

Deferred to Batch 4: true Simulation replay/live dual-mode behavior, per-request scenario/UE/cell/slice application, seeded replay, and truthful readiness semantics for those modes.

Deferred to Batch 7: root `docker-compose.yml`, root `deploy.sh`, one-click network creation, and final service dependency ordering.
