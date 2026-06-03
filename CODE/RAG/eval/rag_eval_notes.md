# TelcoMind RAG Evaluation Notes

Milestone 19/20 scope: lightweight, evidence-oriented notes for Member 2 RAG
quality, retrieval behavior, citation readiness, operational expectations, and
known limits. This is not a formal GenAIEval score or benchmark harness.

## Corpus Status

The local knowledge base is organized under `CODE/RAG/knowledge_base/` and is
indexed by `POST /ingest`.

- `runbooks/`: operational guidance for handover failures, energy optimization,
  and interference troubleshooting.
- `scenarios/`: scenario mapping for simulation-aware retrieval and KPI-aware
  synthesis.
- `specs/`: official source PDFs for 3GPP, ETSI/O-RAN architecture, and O-RAN
  WG1 use cases.

Current spec coverage includes 3GPP NG-RAN architecture and NR/RRC references,
3GPP network resource model and performance measurement references, ETSI O-RAN
architecture, and official O-RAN WG1 use-case reports/specs:

- `3gpp_ts_38_401_ng_ran_architecture.pdf`
- `3gpp_ts_38_300_nr_ng_ran_overall_description.pdf`
- `3gpp_ts_38_331_nr_rrc_protocol.pdf`
- `3gpp_ts_28_541_5g_network_resource_model.pdf`
- `3gpp_ts_28_552_5g_performance_measurements.pdf`
- `etsi_ts_103_982_oran_architecture_description.pdf`
- `oran_wg1_use_cases_detailed_specification.pdf`
- `oran_wg1_use_cases_analysis_report.pdf`

## Retrieval Pipeline

Default local retrieval uses:

- Embedding model: `BAAI/bge-base-en-v1.5`
- Vector database: persistent Chroma collection `telcomind_knowledge`
- Reranker model: `BAAI/bge-reranker-base`
- Initial vector retrieval: `TOP_K=8`
- Final reranked context: `RERANK_TOP_K=4`

The service accepts optional OPEA-style external embedding and reranker
endpoints. These are readiness hooks for integration work, not requirements for
the current local demo. If an external endpoint is missing, invalid, or times
out, the code falls back to the local embedding or reranker path. Reranking can
also be disabled with `RERANKER_BACKEND=disabled`.

Citation-ready retrieval is exposed through `/v1/retrievaltool/json` and
`/synthesize`. Source metadata preserves `source`, `title`, `section`, `score`,
`kind`, `source_type`, `chunk`, and `page` where present. PDF chunks carry
`source_type=spec` and page metadata. Scenario chunks carry
`source_type=scenario`. JSON runbooks carry `kind=runbook`.

## Chunking Choices

Current chunking uses a deterministic sliding text window:

- Chunk size: `1400` characters
- Overlap: `220` characters
- Text normalization: whitespace collapsed before chunking

PDFs are chunked page by page, with each chunk labeled by page number. Markdown
scenario files are split by headings before chunking, so retrieval can surface a
more meaningful section label.

Vector IDs are deterministic SHA-256 digests of source, section, and chunk text.
This matters because repeated ingests update the same Chroma records instead of
creating duplicate IDs for unchanged content. The tradeoff is that meaningful
text or section edits intentionally produce new IDs, so clearing old storage may
be useful after large corpus rewrites.

Known chunking tradeoffs:

- Character windows are simple and robust, but not clause-aware.
- Page-level PDF extraction depends on the text quality exposed by `pypdf`.
- Overlap helps preserve context across boundaries, but can repeat evidence
  when adjacent chunks are both retrieved.

## Demo Query Coverage

The curated demo/eval query set lives in `CODE/RAG/eval/rag_demo_queries.json`.
It contains at least 10 queries across:

- `GENERAL_QNA`
- `DIAGNOSTIC`
- `OPTIMIZATION`

Coverage intentionally includes handover, energy optimization, interference and
hotspot diagnosis, baseline behavior, NG-RAN architecture, O-RAN architecture,
standards/spec citation retrieval, simulation KPI-aware synthesis, and
standards-backed recommendations.

## Quality Criteria

Review retrieval and synthesis output against these criteria:

- Sources should include title, section, page, chunk, and kind/source type when
  those fields are present in the indexed document metadata.
- Synthesis must not invent 3GPP or O-RAN clause numbers.
- Deterministic fallback synthesis must remain available and must not require a
  live LLM service.
- LLM-backed synthesis may replace the answer text, but it must preserve the
  deterministic citations, assumptions, recommended action, KPI fields, intent
  type, and retrieval context count.
- Confidence is a retrieval/synthesis signal, not proof of root cause.

## Latency And Operational Notes

- RAG runs locally on port `7001`.
- vLLM, when used, runs separately on port `8080` and is optional for
  `/synthesize`.
- CPU-mode RAG embeddings are slower than GPU embeddings but stable in the RTX
  5070 Ti environment used for this demo.
- First ingest after adding or replacing PDFs can take time because chunks must
  be extracted, embedded, and upserted into Chroma.
- Local Chroma storage should be rebuilt if the embedding model family or
  embedding dimensionality changes.

## Known Limitations

- These notes are lightweight evaluation documentation, not a formal GenAIEval
  score.
- Official source PDFs are included, but exact clause-level accuracy depends on
  the retrieved chunk and the source text extracted from the PDF.
- The local vLLM demo model is `Qwen/Qwen2.5-0.5B-Instruct`; answer quality may
  be weaker than larger 7B/8B models.
- External OPEA embedding/reranker endpoints are optional readiness hooks, not
  required for the current local demo.
- Retrieval quality should be manually spot-checked after adding new standards
  PDFs or changing chunking parameters.

## Suggested Manual Evaluation Commands

Run offline checks:

```bash
cd CODE
source .venv/bin/activate
python -m compileall RAG
pytest RAG/tests -q
```

Start RAG:

```bash
cd CODE/RAG
RAG_DEVICE=cpu ../.venv/bin/uvicorn app.rag_service:app --host 0.0.0.0 --port 7001
```

Ingest and check health:

```bash
curl -X POST http://localhost:7001/ingest
curl http://localhost:7001/health
```

Sample retrieval check:

```bash
curl -X POST http://localhost:7001/v1/retrievaltool/json \
  -H "Content-Type: application/json" \
  -d '{"text":"Which NG-RAN architecture references explain gNB, NG-C, NG-U, and interface responsibilities?"}'
```

Sample deterministic synthesis check:

```bash
curl -X POST http://localhost:7001/synthesize \
  -H "Content-Type: application/json" \
  -d '{
    "query":"Given simulation KPIs showing high PRB utilization, low SINR, and poor throughput in a hotspot, is this congestion or interference?",
    "intent_type":"DIAGNOSTIC",
    "simulation_kpis":{
      "prb_utilization":0.91,
      "sinr_db":4.2,
      "throughput_mbps":18.5
    }
  }'
```

Optional vLLM-enabled synthesis check after starting vLLM on port `8080`:

```bash
cd CODE/RAG
LLM_ENABLED=true \
LLM_ENDPOINT_URL=http://localhost:8080 \
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct \
RAG_DEVICE=cpu \
../.venv/bin/uvicorn app.rag_service:app --host 0.0.0.0 --port 7001
```

Then rerun the sample `/synthesize` request and confirm that citations and
metadata fields remain present even when the answer text is LLM-backed.
