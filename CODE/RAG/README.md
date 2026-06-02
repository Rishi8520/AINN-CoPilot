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

## Known Limitations

- Synthesis currently uses a deterministic fallback, not full LLM synthesis yet.
- Local Chroma storage is ignored by git.
- GPU is disabled until a compatible PyTorch/vLLM setup is available.
- Official standards PDFs must be added separately.
