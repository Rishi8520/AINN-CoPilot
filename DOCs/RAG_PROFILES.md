# RAG Profiles

TelcoMind RAG accepts exactly two profiles: `quickstart` and `full`.

| Profile | Purpose | Retrieval backend | Corpus/index | Startup behavior | Readiness |
| --- | --- | --- | --- | --- | --- |
| `quickstart` | Default submission-oriented offline demo | Deterministic lexical BM25-style ranking | `CODE/RAG/quickstart/corpus.jsonl` plus `manifest.json` | No Chroma, BGE, reranker, CUDA, vLLM, model download, or full PDF ingestion | Validates corpus, manifest, source hashes, chunk hashes, and lexical backend |
| `full` | Advanced semantic RAG path | Chroma vector retrieval with BGE embeddings and optional reranking | Existing non-empty Chroma collection under `RAG_FULL_INDEX_PATH` | Does not auto-ingest; initializes full dependencies only for full profile use | Requires dependencies, configured index path, and usable non-empty collection |

## Environment

- `RAG_PROFILE=quickstart`
- `RAG_QUICKSTART_CORPUS_PATH=quickstart/corpus.jsonl`
- `RAG_QUICKSTART_TOP_K=5`
- `RAG_FULL_INDEX_PATH=/data/chroma` in Docker, or `storage/chroma` for native `CODE/RAG`
- `RAG_AUTO_INGEST=false`
- `RAG_STRICT_PROVENANCE=true`

Legacy `CHROMA_DIR` is still read as a full-profile index-path alias when `RAG_FULL_INDEX_PATH` is absent. `LLM_BASE_URL` is the canonical optional OpenAI-compatible synthesis URL. `VLLM_BASE_URL` and `LLM_ENDPOINT_URL` remain legacy aliases only when `LLM_BASE_URL` is absent or empty.

## API Metadata

Structured retrieval responses include `rag_profile`, `retrieval_backend`, `corpus_id` or `index_id`, `result_count`, `fallback_used`, and `warnings`. Source chunks preserve citation fields: `source`, `title`, `section`, `chunk`, `page`, `kind`, and `source_type`.

Quickstart lexical BM25 scores are raw ranking scores. They are not confidence, probability, calibrated scores, or semantic similarity.

In the Batch 7 root Compose quickstart, the `rag` service uses
`CODE/RAG/Dockerfile.quickstart`. The image copies the quickstart corpus and
the committed source files referenced by `quickstart/manifest.json` so strict
provenance can validate source hashes. Startup does not run `/ingest`, build
Chroma, initialize BGE embeddings, initialize a reranker, download model
weights, or contact vLLM.

## Health And Readiness

- `GET /health` is process liveness only.
- `GET /ready` returns `200` only when the configured profile and synthesis policy are ready. Unavailable `full` mode returns `503`; it does not use quickstart as a substitute. Optional OpenAI-compatible synthesis with deterministic fallback may be reported as degraded-ready when its LLM config is incomplete.
- `GET /capabilities` reports supported profiles and synthesis backends without claiming an OpenAI-compatible endpoint is reachable based only on URL presence.

## Offline Evaluator

From `CODE/RAG`:

```bash
python scripts/build_quickstart_corpus.py --verify
python scripts/evaluate_quickstart.py
```

The evaluator reports query, returned chunk IDs, source types, rank positions, expected-evidence presence, profile/backend, and latency. It is a sanity check, not a competition benchmark or formal performance claim.

## Full Ingestion

Full semantic ingestion remains explicit:

```bash
RAG_PROFILE=full python scripts/ingest.py
```

Do not run this as part of quickstart startup. Full ingestion may load BGE models, write Chroma storage, and take materially longer than the quickstart profile.

## What Quickstart Proves

- The RAG API can start in an offline CPU-safe profile once Python dependencies are present.
- Retrieval uses a committed, traceable corpus derived from existing repository sources.
- Citation metadata survives retrieval and deterministic synthesis.
- Synthesis defaults to `synthesis_backend=deterministic` with `llm_used=false`.
- No Chroma index, model download, vLLM/OpenAI-compatible endpoint, Docker startup, or full PDF ingestion is needed.

## What Quickstart Does Not Prove

- It does not prove full semantic retrieval quality.
- It does not prove BGE embedding or reranker availability.
- It does not prove a fresh full Chroma index can be built quickly.
- It does not prove under-10-minute four-core setup timing.
- It does not prove vLLM or GPU behavior.
- It does not prove optional OpenAI-compatible LLM reachability or output quality.

The full semantic profile remains the production/advanced retrieval path.
