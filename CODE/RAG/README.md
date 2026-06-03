# TelcoMind Member 2: RAG & Knowledge

This service provides the TelcoMind Retrieval-Augmented Generation (RAG)
knowledge layer. It indexes local runbooks, scenario markdown, and official
specification PDFs, then exposes retrieval and synthesis endpoints for the
Agent, UI, and teammate demos.

Current status:

- Runs locally on port `7001`.
- `/health` reports service readiness.
- `/ingest` indexes runbooks, scenarios, and PDFs under `knowledge_base/specs/`.
- `/v1/retrievaltool` returns Agent-compatible plain text.
- `/v1/retrievaltool/json` returns citation-ready JSON.
- `/synthesize` returns structured synthesis with answer, confidence,
  citations, assumptions, recommended action, KPI usage, intent type, and
  retrieval context count.

## Local Startup

Use CPU mode for the current local setup:

```bash
cd CODE/RAG
RAG_DEVICE=cpu ../.venv/bin/uvicorn app.rag_service:app --host 0.0.0.0 --port 7001
```

`RAG_DEVICE=cpu` is currently recommended because the RTX 5070 Ti requires
`sm_120` support, and the current PyTorch setup is not compatible with that GPU
target yet. GPU optimization can be added later after a compatible PyTorch/vLLM
stack is available.

## Endpoints

- `GET /health`
- `POST /ingest`
- `POST /retrieve`
- `POST /v1/retrievaltool`
- `POST /v1/retrievaltool/json`
- `POST /synthesize`

## Embedding And Reranker Backends

By default, RAG uses local `sentence-transformers` models in-process:

```env
EMBEDDING_BACKEND=local
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RERANKER_BACKEND=local
RERANKER_MODEL=BAAI/bge-reranker-base
```

This is the source-of-truth path for the current local demo. It requires no
external embedding or reranker microservices.

RAG can also be pointed at OPEA-style external embedding and reranker services
without changing the retrieval API:

```env
EMBEDDING_BACKEND=external
EMBEDDING_ENDPOINT_URL=http://localhost:6000/embed
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
EMBEDDING_TIMEOUT_SECONDS=30

RERANKER_BACKEND=external
RERANKER_ENDPOINT_URL=http://localhost:6001/rerank
RERANKER_MODEL=BAAI/bge-reranker-base
RERANKER_TIMEOUT_SECONDS=30
```

If an external endpoint is not configured, times out, fails, returns invalid
JSON, or returns an invalid shape, RAG falls back to the local model path. Set
`RERANKER_BACKEND=disabled` to skip reranking and return vector-search scores
only.

Expected external embedding request:

```json
{
  "model": "BAAI/bge-base-en-v1.5",
  "input": [
    "first chunk or query",
    "second chunk"
  ]
}
```

Supported embedding responses:

```json
{
  "embeddings": [
    [0.012, -0.034, 0.056],
    [0.078, -0.09, 0.012]
  ]
}
```

OpenAI-style `data` responses are also accepted:

```json
{
  "data": [
    {"embedding": [0.012, -0.034, 0.056]},
    {"embedding": [0.078, -0.09, 0.012]}
  ]
}
```

Expected external reranker request:

```json
{
  "model": "BAAI/bge-reranker-base",
  "query": "Why did handover failures increase?",
  "documents": [
    "candidate chunk one",
    "candidate chunk two"
  ]
}
```

Supported reranker responses:

```json
{
  "scores": [0.42, 0.91]
}
```

Indexed result responses are also accepted:

```json
{
  "results": [
    {"index": 0, "score": 0.42},
    {"index": 1, "score": 0.91}
  ]
}
```

The external embedding dimension must match the dimension already stored in the
Chroma collection. If Member 3 changes the embedding service or model family,
rebuild the collection with `/ingest` after clearing the old local Chroma
storage.

## Curl Examples

Health:

```bash
curl http://localhost:7001/health
```

Ingest knowledge base:

```bash
curl -X POST http://localhost:7001/ingest
```

Agent-compatible plain-text retrieval:

```bash
curl -X POST http://localhost:7001/v1/retrievaltool \
  -H "Content-Type: application/json" \
  -d '{"text":"What causes handover failures in 5G NR?"}'
```

Citation-ready JSON retrieval:

```bash
curl -X POST http://localhost:7001/v1/retrievaltool/json \
  -H "Content-Type: application/json" \
  -d '{"text":"What causes handover failures in 5G NR?"}'
```

Synthesis without simulation KPIs:

```bash
curl -X POST http://localhost:7001/synthesize \
  -H "Content-Type: application/json" \
  -d '{"query":"How should we troubleshoot high latency in a 5G cell?"}'
```

Synthesis with simulation KPIs:

```bash
curl -X POST http://localhost:7001/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "query":"Why is this cell showing poor handover performance?",
    "simulation_kpis":{
      "handover_success_rate":0.82,
      "average_latency_ms":38.5,
      "packet_loss_rate":0.018
    }
  }'
```

## Optional vLLM Synthesis

By default, `/synthesize` uses deterministic synthesis only. This keeps local
RAG startup independent from any LLM service:

```env
LLM_ENABLED=false
```

To enable OpenAI-compatible vLLM synthesis, start vLLM separately:

```powershell
docker run --rm --name vllm-inference --gpus all --ipc=host `
  --ulimit memlock=-1 --ulimit stack=67108864 `
  -p 8080:8000 `
  -v $env:USERPROFILE\.cache\huggingface:/root/.cache/huggingface `
  -e NCCL_P2P_DISABLE=1 `
  -e CUDA_MODULE_LOADING=LAZY `
  nvcr.io/nvidia/vllm:26.05.post1-py3 `
  vllm serve Qwen/Qwen2.5-0.5B-Instruct `
  --port 8000 `
  --host 0.0.0.0 `
  --dtype float16 `
  --max-model-len 2048 `
  --max-num-seqs 1 `
  --enforce-eager `
  --gpu-memory-utilization 0.60
```

Then start RAG with LLM synthesis enabled:

```bash
cd CODE/RAG
LLM_ENABLED=true \
LLM_ENDPOINT_URL=http://localhost:8080 \
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct \
RAG_DEVICE=cpu \
../.venv/bin/uvicorn app.rag_service:app --host 0.0.0.0 --port 7001
```

Environment variables:

- `LLM_ENABLED`: defaults to `false`.
- `LLM_ENDPOINT_URL`: defaults to empty. When enabled, RAG posts to
  `{LLM_ENDPOINT_URL}/v1/chat/completions`.
- `LLM_MODEL`: defaults to `Qwen/Qwen2.5-0.5B-Instruct`.
- `LLM_TIMEOUT_SECONDS`: defaults to `30`.

When vLLM is enabled and returns a usable answer, `/synthesize` uses that text
as `answer` while preserving deterministic citations, assumptions,
recommended action, KPI fields, intent type, and retrieval context count. If
vLLM is offline, times out, returns invalid JSON, or returns no usable answer,
the API still succeeds with deterministic fallback synthesis and records an
assumption noting that fallback was used.

## Agent Integration Contract

Set the Agent service URL to the RAG host and port:

```env
RAG_SERVICE_URL=http://<host>:7001
```

Agent tool calls should use:

```text
POST /v1/retrievaltool
```

This endpoint returns plain text that is compatible with the existing Agent
tooling. UI and synthesis workflows can use `/v1/retrievaltool/json` for
citation-ready retrieval or `/synthesize` for structured answers.

## Knowledge Base Layout

```text
CODE/RAG/knowledge_base/
  runbooks/
  scenarios/
  specs/
```

Put official standards PDFs in:

```text
CODE/RAG/knowledge_base/specs/
```

Then run `/ingest` again.

Current spec coverage includes 3GPP NG-RAN architecture, NR/RRC, network
resource model, performance measurements, ETSI O-RAN architecture, and official
O-RAN WG1 use-case sources:

- `oran_wg1_use_cases_detailed_specification.pdf`
- `oran_wg1_use_cases_analysis_report.pdf`

## Tests

Run these from WSL or a compatible Linux shell:

```bash
cd CODE
source .venv/bin/activate
python -m compileall RAG
pytest RAG/tests -q
```

Demo queries live at:

```text
CODE/RAG/eval/rag_demo_queries.json
```

The curated demo/eval set contains at least 10 intents covering `GENERAL_QNA`,
`DIAGNOSTIC`, and `OPTIMIZATION` flows. Coverage includes handover failure,
energy optimization, interference or hotspot diagnosis, NG-RAN architecture,
O-RAN architecture, standards/spec citation retrieval, and simulation
KPI-aware synthesis.

Lightweight Member 2 RAG quality and evaluation notes live at:

```text
CODE/RAG/eval/rag_eval_notes.md
```

These notes summarize corpus coverage, chunking, retrieval/reranking behavior,
citation readiness, demo query coverage, latency expectations, and manual
evaluation commands for teammate or judge handoff.

## Known Limitations

- LLM synthesis is optional and depends on an external OpenAI-compatible vLLM
  endpoint; deterministic fallback remains the default.
- Local Chroma storage is ignored by git.
- GPU is disabled until a compatible PyTorch/vLLM setup is available.
- Additional official standards PDFs can be added separately as coverage grows.
