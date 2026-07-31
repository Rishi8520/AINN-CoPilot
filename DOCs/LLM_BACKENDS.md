# LLM Backends

TelcoMind synthesis has two supported runtime backends:

| Backend | Default | Uses a model | Uses network | Typical use |
| --- | --- | --- | --- | --- |
| `deterministic` | Yes | No | No | CPU-safe submission quickstart and offline validation |
| `openai_compatible` | No | Yes, via configured service | Yes, to configured endpoint only | Optional LLM synthesis through vLLM, an OPEA-compatible LLM service, or another `/v1/chat/completions` implementation |

Deterministic synthesis is not LLM output. It summarizes retrieved evidence and supplied KPI context with structured citations. It is the submission default because it does not require a GPU, model download, external service, API key, or network.

## Configuration

```env
RAG_SYNTHESIS_BACKEND=deterministic
LLM_BASE_URL=
LLM_PROVIDER=openai_compatible
LLM_MODEL=
LLM_API_KEY=
LLM_REQUIRED=false
LLM_FALLBACK_TO_DETERMINISTIC=true
LLM_CONNECT_TIMEOUT_SECONDS=3
LLM_READ_TIMEOUT_SECONDS=30
LLM_MAX_TOKENS=512
LLM_TEMPERATURE=0
```

Accepted `RAG_SYNTHESIS_BACKEND` values are exactly `deterministic` and `openai_compatible`. Empty values become `deterministic`; invalid values fail configuration.

`LLM_BASE_URL` is canonical. `VLLM_BASE_URL` and `LLM_ENDPOINT_URL` are legacy aliases only when `LLM_BASE_URL` is absent or empty. The client posts to exactly `<base-url>/v1/chat/completions`, avoiding duplicate `/v1` path segments and double slashes.

No API key is required for unauthenticated local endpoints. If `LLM_API_KEY` is set, it is sent as an Authorization bearer token and is not returned in config, capabilities, failures, logs, or examples.

## Policy

Deterministic mode always returns:

```json
{
  "requested_backend": "deterministic",
  "synthesis_backend": "deterministic",
  "llm_used": false,
  "fallback_used": false
}
```

Successful OpenAI-compatible mode returns:

```json
{
  "requested_backend": "openai_compatible",
  "synthesis_backend": "openai_compatible",
  "llm_used": true,
  "fallback_used": false,
  "configured_provider": "openai_compatible",
  "configured_model": "configured-model",
  "response_model": "model-returned-by-service"
}
```

Optional LLM failures fall back only when `LLM_REQUIRED=false` and `LLM_FALLBACK_TO_DETERMINISTIC=true`. Required LLM failures and fallback-disabled failures return a structured service failure instead of deterministic text.

## Client Behavior

The OpenAI-compatible client uses `httpx` with explicit connect and read timeouts, `temperature=0` by default, bounded `max_tokens`, and defensive response parsing. It treats connection errors, DNS failures, connect/read timeouts, 401/403, 404, 429, 5xx, malformed JSON, missing/empty choices, missing message content, empty content, and unexpected content type as failures. Malformed output is never reported as successful LLM synthesis.

## Grounding And Citations

Prompts include only the user request, explicit KPI/context fields, retrieved chunks, citation IDs, and concise system instructions. Evidence blocks are delimited and labelled with stable IDs such as `[C1]`. Local filesystem paths and source SHA-256 values are not sent.

Responses preserve structured citation objects separately from model prose. Citation validation reports `citation_validation=passed|warned|failed` and `unknown_citation_ids`. Unknown IDs are flagged and are not remapped to arbitrary sources.

## Prompt-Injection Mitigation

Retrieved text is treated as data, not instructions. The system prompt tells the model to ignore commands embedded in evidence, not invent citations or KPI values, and state uncertainty when evidence is insufficient. This is a focused mitigation, not a guarantee of complete prompt-injection resistance.

## Health, Readiness, Capabilities

- `/health` is process liveness only and does not probe the LLM.
- `/ready` includes configured synthesis policy. Deterministic mode is ready. Optional OpenAI-compatible mode with missing config is degraded-ready only when deterministic fallback is allowed. Required or fallback-disabled OpenAI-compatible mode with missing config is not ready.
- `/capabilities` reports supported synthesis backends, configured backend, deterministic availability, provider/model configuration status, required/fallback policy, and `endpoint_reachability=not_checked`. It does not expose secrets or claim reachability based only on URL presence.

## Optional Local GPU vLLM

vLLM is one optional OpenAI-compatible implementation. It is not part of default startup, does not run in quickstart, and requires separate GPU/NVIDIA Container Toolkit support.

The Batch 7 root Compose file keeps vLLM behind the optional `gpu-llm` profile
on port `8080`. The profile is not pulled, built, started, or required by the
default deployment scripts, and remains unverified in this batch.

Development-tested reference path only:

```powershell
docker run --rm --name vllm-inference --gpus all --ipc=host `
  --ulimit memlock=-1 --ulimit stack=67108864 `
  -p 8080:8000 `
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

Then configure RAG explicitly:

```env
RAG_SYNTHESIS_BACKEND=openai_compatible
LLM_PROVIDER=vllm
LLM_BASE_URL=http://localhost:8080
LLM_MODEL=Qwen/Qwen2.5-0.5B-Instruct
LLM_REQUIRED=false
LLM_FALLBACK_TO_DETERMINISTIC=true
```

This path was not run in this batch and is not an evaluator requirement.

## OPEA Compatibility Scope

Implemented interface compatibility:

- RAG exposes an OPEA retrievaltool-compatible endpoint at `/v1/retrievaltool`.
- Structured retrieval is available at `/v1/retrievaltool/json`.
- OpenAI-compatible synthesis can address an OPEA-compatible LLM service that implements `/v1/chat/completions`.
- Full-profile embedding/reranker settings can point to external OPEA-style services.

Verification level: offline unit and contract tests with mocked HTTP calls. No formal OPEA certification, end-to-end OPEA deployment, vLLM runtime, GPU execution, model download, or external API call was verified in this batch.
