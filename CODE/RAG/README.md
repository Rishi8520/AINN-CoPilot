# TelcoMind Member 2: RAG + LLM

This folder is for Member 2's machine. It exposes:

- RAG retrieval API on `:7000`
- vLLM OpenAI-compatible API on `:8080`

Member 3's Agent should call these over Tailscale:

```env
RAG_SERVICE_URL=http://member2-tailscale-name:7000
RAG_HEALTH_PATH=/health
LLM_ENDPOINT_URL=http://member2-tailscale-name:8080
```

## Hardware Target

Member 2 has RTX 5070 Ti, 12 GB VRAM, 32 GB RAM, Intel Core Ultra 9 275 HX.

The default LLM is `Qwen/Qwen2.5-7B-Instruct`, which is a practical 7B-class
model for a 12 GB GPU. If vLLM fails due to memory, reduce `--max-model-len` in
`docker-compose.yml` or choose a smaller instruct model.

## First Run

```bash
cd CODE/RAG
cp .env.example .env
docker compose up -d --build rag-service
```

Put PDFs in:

```text
knowledge_base/specs/
```

Run ingestion:

```bash
curl -X POST http://localhost:7000/ingest
```

Test retrieval:

```bash
curl -X POST http://localhost:7000/v1/retrievaltool \
  -H "Content-Type: application/json" \
  -d '{"text":"What causes handover failures in 5G NR?"}'
```

Start vLLM:

```bash
docker compose up -d vllm
```

Test vLLM:

```bash
curl http://localhost:8080/v1/models
```

## Tailscale Test From Member 3

From Rishi's machine:

```bash
curl http://member2-tailscale-name:7000/health
curl http://member2-tailscale-name:8080/v1/models
```

## Endpoints

- `GET /health`
- `POST /ingest`
- `POST /retrieve`
- `POST /v1/retrievaltool`

`/v1/retrievaltool` is compatible with the existing Agent tool code, which sends:

```json
{"text": "query here"}
```
