# Deployment

TelcoMind Batch 7 adds a root, single-node Docker Compose quickstart. The default stack is CPU-safe and starts five required services: Simulation replay, RAG quickstart, Agent, Gateway, and Streamlit UI.

## Prerequisites

- Docker Desktop or Docker Engine with Docker Compose v2.
- No GPU is required.
- No Tailscale is required.
- No API key, model download, full PDF ingestion, Chroma rebuild, or live Simu5G execution is required.

Tested CLI availability on this host: Docker CLI `29.5.2`, Docker Compose `v5.1.4`. Daemon access still depends on the local Docker Desktop/pipe permissions at runtime.

## Commands

PowerShell:

```powershell
.\deploy.ps1
.\deploy.ps1 -Status
.\deploy.ps1 -Logs
.\deploy.ps1 -Verify
.\deploy.ps1 -Down
```

Bash, WSL, Linux, or macOS:

```bash
./deploy.sh
./deploy.sh --status
./deploy.sh --logs
./deploy.sh --verify
./deploy.sh --down
```

Direct Compose:

```bash
docker compose up -d --build
python scripts/smoke_test.py
```

## Architecture

| Service | Container DNS | Host URL | Health |
| --- | --- | --- | --- |
| Simulation | `http://simulation:7000` | `http://localhost:7000` | `/health`, `/ready` |
| RAG | `http://rag:7001` | `http://localhost:7001` | `/health`, `/ready` |
| Agent | `http://agent:9090` | `http://localhost:9090` | `/v1/health_check` |
| Gateway | `http://gateway:8888` | `http://localhost:8888` | `/v1/health`, `/health` |
| UI | `http://ui:8501` | `http://localhost:8501` | `/healthz` |

Startup order is health-gated: Simulation and RAG, then Agent, then Gateway, then UI. Service-to-service traffic uses Compose DNS names, not host-published ports.

## Defaults

- `SIMULATION_DEFAULT_MODE=replay`
- `SIMULATION_REPLAY_FIXTURE=phase_bootstrap_normal`
- `SIMULATION_LIVE_ENABLED=false`
- `RAG_PROFILE=quickstart`
- `RAG_AUTO_INGEST=false`
- `RAG_SYNTHESIS_BACKEND=deterministic`
- `LLM_REQUIRED=false`
- `LLM_BASE_URL=`

The RAG quickstart image copies the committed quickstart corpus and source knowledge-base files so strict provenance hashes can be checked. It does not ingest PDFs, initialize Chroma, load BGE, load a reranker, or call vLLM.

## Troubleshooting

- Port occupied: set `HOST_SIMULATION_PORT`, `HOST_RAG_PORT`, `HOST_AGENT_PORT`, `HOST_GATEWAY_PORT`, or `HOST_UI_PORT`, then redeploy.
- Docker daemon unavailable: start Docker Desktop and confirm `docker info` works from the same shell.
- Unhealthy service: run `.\deploy.ps1 -Logs` or `./deploy.sh --logs`; failed deploys print targeted logs automatically.
- Image build failure: check the first pip or copy error in the build log; quickstart images do not install runtime dependencies at container start.
- CRLF or shebang issue: `deploy.sh` is normalized to LF by `.gitattributes`.
- Low memory: stop unrelated containers and rerun; default services are Python slim images and avoid model loads.

## Optional Advanced Modes

The root Compose includes an optional `gpu-llm` profile for vLLM on port `8080`. It is not started, pulled, built, or required by default, and it was not validated in this batch. Full RAG and live Simu5G remain component-level advanced paths documented in `DOCs/RAG_PROFILES.md`, `DOCs/SIMULATION_MODES.md`, and `DOCs/LLM_BACKENDS.md`.

## Verified Scope

This deployment is intended to prove the UI/Gateway/Agent/RAG/Simulation quickstart flow with replay provenance, lexical retrieval metadata, and deterministic synthesis metadata. It does not prove live Simu5G, full semantic RAG, vLLM/GPU behavior, OPEA certification, teammate-machine networking, or formal under-10-minute setup timing. Controlled timing evidence is deferred to Batch 10.
