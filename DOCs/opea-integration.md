# OPEA Reasoning Integration

The existing job orchestrator owns simulation submission, progress, cancellation,
retrieval, and artifact downloads. The RAG synthesis step calls the real OPEA
agent microservice with collected evidence and measured experiment context.
OPEA's react_langgraph strategy generates the final explanation using OpenAI.
It has no tools and no conversation memory, so it cannot rerun experiments or
mix evidence between jobs. This is OPEA-backed reasoning, not OPEA ownership of
the entire orchestration workflow.

## Deployment

This overlay requires Docker Compose 2.24.4 or newer for port overrides.
Published ports are bound to localhost to avoid exposing a paid model workflow
to the LAN. Do not expose these unauthenticated APIs publicly; remote deployment
needs a separate authenticated access layer and spending controls.

Set `LLM_API_KEY` and `LLM_MODEL` privately in `CODE/.env` or repository-root `.env`.
The original GPT-5 family (`gpt-5`, `gpt-5-mini`, `gpt-5-nano`, including dated
snapshots) is supported through a small bootstrap that retains the actual OPEA
agent graph but omits unsupported temperature/top_p parameters. LangChain emits
`max_completion_tokens`. Other models retain the upstream configuration.
For GPT-5, `OPEA_MAX_COMPLETION_TOKENS=4096` caps reasoning plus visible output;
`OPEA_REASONING_EFFORT=minimal` is the default. The cap is not a guaranteed token
usage, and increasing it can increase cost. Configure these in the selected env
file; `LLM_MAX_TOKENS` continues to control other models. Support for other
reasoning families is not implied.
Both deployment scripts prefer root `.env` when present; otherwise they use
`CODE/.env`. They pass the selected path explicitly to Compose without copying
or sourcing credentials. When both exist, they do not merge the files.
Do not print resolved Compose configuration or commit credentials.

```bash
./deploy.sh --opea
./deploy.sh --opea --status
./deploy.sh --opea --verify
```

PowerShell: `./deploy.ps1 -Opea`, with optional `-Status` or `-Verify`.
Recorded replay remains selectable per query in the live frontend.

The overlay pins the inspected OPEA image by digest and exposes it only on the
internal Docker network. OpenAI credentials go to OPEA, not the RAG adapter.
The OPEA URL is distinct from the OpenAI model URL. The image appends `/v1` to
the model base URL; the overlay sets `https://api.openai.com` accordingly.
The lowercase `api_key` argument is deliberately unused because upstream logs
parsed arguments. `OPENAI_API_KEY` is consumed by its OpenAI SDK instead.

Normal `./deploy.sh` remains the existing deterministic live workflow. Switching
back recreates RAG with its configured default; an unused OPEA container may
remain until `./deploy.sh --opea --down` removes this project's services.

## Verification and Limitations

Confirm a completed response has `requested_backend=opea_agent`,
`synthesis_backend=opea_agent`, `llm_used=true`, `fallback_used=false`, and
`citation_validation=passed`. The UI displays the actual synthesis backend.
Required OPEA mode rejects network errors, malformed envelopes, exception strings
returned with HTTP 200, and missing/unknown citation IDs. It never silently
claims success through a deterministic fallback. Citation validation checks IDs,
not the semantic correctness of every generated claim; inspect the sources.

Health checks establish that the OPEA HTTP API is served, not that the OpenAI
account, billing, model access, or generation work. A real query performs paid
inference. Cancellation stops our job workflow but cannot guarantee cancellation
of an OpenAI request already accepted upstream. Evidence and measurements are
sent to OpenAI: use only data approved for that service.

Integration tests use mocked completions and fake credentials without billing.
Real account verification requires the operator's explicit live run.
Deployment verification makes several paid model requests, not just health probes.
This step does not resolve simulator licensing, publish images, or establish a ten-minute
clean-install guarantee.
