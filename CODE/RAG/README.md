# TelcoMind Member 2: RAG & Knowledge

This service provides the TelcoMind Retrieval-Augmented Generation (RAG)
knowledge layer. It exposes retrieval and synthesis endpoints for the Agent,
UI, and teammate demos with two explicit profiles: default offline
`quickstart` and advanced semantic `full`.

Current status:

- Runs locally on port `7001`.
- `/health` reports process liveness only.
- `/ready` reports configured-profile readiness.
- `/capabilities` reports profile/backend support.
- `/ingest` explicitly indexes runbooks, scenarios, and PDFs only in `RAG_PROFILE=full`.
- `/v1/retrievaltool` returns Agent-compatible plain text.
- `/v1/retrievaltool/json` returns citation-ready JSON.
- `/synthesize` returns structured synthesis with answer, confidence,
  citations, assumptions, recommended action, KPI usage, intent type, and
  retrieval context count plus truthful backend, fallback, and citation
  validation metadata.

## Local Startup

Use the CPU-safe offline quickstart profile for the current local setup:

```bash
cd CODE/RAG
RAG_PROFILE=quickstart RAG_DEVICE=cpu ../.venv/bin/uvicorn app.rag_service:app --host 0.0.0.0 --port 7001
```

Quickstart does not initialize Chroma, BGE embeddings, the reranker, CUDA,
vLLM, model downloads, or full PDF ingestion. It uses
`quickstart/corpus.jsonl` and deterministic lexical BM25-style ranking.

## Endpoints

- `GET /health`
- `GET /ready`
- `GET /capabilities`
- `POST /ingest`
- `POST /retrieve`
- `POST /v1/retrievaltool`
- `POST /v1/retrievaltool/json`
- `POST /synthesize`

## Profiles

```env
RAG_PROFILE=quickstart
RAG_QUICKSTART_CORPUS_PATH=quickstart/corpus.jsonl
RAG_QUICKSTART_TOP_K=5
RAG_AUTO_INGEST=false
RAG_STRICT_PROVENANCE=true
```

`quickstart` is the default. It is offline and CPU-safe once Python
dependencies are available. Retrieval responses identify
`rag_profile=quickstart`, `retrieval_backend=lexical_bm25`, `corpus_id`, result
count, warnings, and `fallback_used=false`. Lexical scores are raw BM25 ranking
scores, not confidence, probability, calibrated scores, semantic similarity, or
retrieval quality proof.

`full` preserves the existing Chroma/BGE/reranker path:

```env
RAG_PROFILE=full
RAG_FULL_INDEX_PATH=storage/chroma
RAG_AUTO_INGEST=false
```

Full mode requires an existing non-empty Chroma collection or an explicit
separately invoked ingestion step. If full requirements are missing, `/ready`
and retrieval report unavailable; the service does not silently substitute
quickstart results.

## Embedding And Reranker Backends

In `RAG_PROFILE=full`, RAG can use local `sentence-transformers` models
in-process:

```env
EMBEDDING_BACKEND=local
EMBEDDING_MODEL=BAAI/bge-base-en-v1.5
RERANKER_BACKEND=local
RERANKER_MODEL=BAAI/bge-reranker-base
```

This is the source-of-truth path for the advanced semantic profile. It is not
loaded by the default quickstart profile.

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
JSON, or returns an invalid shape in full mode, RAG falls back to the local
full-profile model path. It does not fall back to the quickstart backend. Set
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

Health and readiness:

```bash
curl http://localhost:7001/health
curl http://localhost:7001/ready
curl http://localhost:7001/capabilities
```

Explicit full-profile ingestion:

```bash
RAG_PROFILE=full curl -X POST http://localhost:7001/ingest
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

## Synthesis Backends

By default, `/synthesize` uses deterministic synthesis only. This keeps local
RAG startup independent from any LLM service, model download, GPU, API key, or
network:

```env
RAG_SYNTHESIS_BACKEND=deterministic
```

Deterministic synthesis reports `requested_backend=deterministic`,
`synthesis_backend=deterministic`, `llm_used=false`, and
`fallback_used=false`. It is not labelled as LLM output.

To enable an OpenAI-compatible LLM endpoint explicitly:

```env
RAG_SYNTHESIS_BACKEND=openai_compatible
LLM_BASE_URL=http://localhost:8080
LLM_PROVIDER=openai_compatible
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
LLM_REQUIRED=false
LLM_FALLBACK_TO_DETERMINISTIC=true
LLM_CONNECT_TIMEOUT_SECONDS=3
LLM_READ_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=512
LLM_TEMPERATURE=0
```

`LLM_BASE_URL` is canonical. `VLLM_BASE_URL` and `LLM_ENDPOINT_URL` remain
legacy aliases only when the canonical URL is absent. The client posts to
`<base-url>/v1/chat/completions`. If `LLM_API_KEY` is set, it is sent as an
Authorization bearer token and is not exposed in responses or capabilities.

Optional LLM failures fall back to deterministic synthesis only when fallback
is allowed. Required or fallback-disabled LLM failures return structured
service failure details and do not imply that any LLM-generated text exists.

### Optional vLLM Reference

vLLM is one optional OpenAI-compatible implementation. It is not part of the
default quickstart and requires separate GPU/NVIDIA Container Toolkit support.
This development-tested command is documentation only for this batch:

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
RAG_SYNTHESIS_BACKEND=openai_compatible \
LLM_PROVIDER=vllm \
LLM_BASE_URL=http://localhost:8080 \
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct \
RAG_DEVICE=cpu \
../.venv/bin/uvicorn app.rag_service:app --host 0.0.0.0 --port 7001
```

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

## Quickstart Corpus

Quickstart files live in:

```text
CODE/RAG/quickstart/
  README.md
  corpus.jsonl
  manifest.json
  demo_queries.json
```

Rebuild or verify the committed corpus offline:

```bash
python scripts/build_quickstart_corpus.py
python scripts/build_quickstart_corpus.py --verify
python scripts/evaluate_quickstart.py
```

The corpus is generated only from committed `knowledge_base` sources and
records source-relative paths, source hashes, chunk hashes, extraction methods,
and PDF pages where used.

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
