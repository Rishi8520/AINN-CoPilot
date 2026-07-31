# TelcoMind Test Matrix

Batch 8 adds a reproducible root test matrix for offline/static validation. The root commands are:

```powershell
.\test.ps1
.\test.ps1 -Fast
.\test.ps1 -StaticOnly
.\test.ps1 -WithSmoke
.\test.ps1 -List
```

```bash
./test.sh
./test.sh --fast
./test.sh --static-only
./test.sh --with-smoke
./test.sh --list
```

## Architecture

`tests/test_matrix.json` is the source of truth. `scripts/run_test_matrix.py` loads it, validates it, and runs each suite as a separate subprocess with an explicit working directory, controlled `PYTHONPATH`, timeout, environment, log file, and JUnit output.

Isolation is required because both `CODE/RAG/app` and `CODE/Simulation/app` are top-level Python packages named `app`. Until the repository is repackaged, RAG and Simulation tests must not run inside one shared Python interpreter.

## Suites

| Suite | Purpose | Working directory | Required |
| --- | --- | --- | --- |
| `root_contracts` | Root deployment and matrix isolation contracts | `.` | Yes |
| `agent` | Agent, Gateway, tools, and UI config with mocked services | `CODE/Agent` | Yes |
| `rag_core` | Quickstart RAG, profiles, and API contracts | `CODE/RAG` | Yes |
| `rag_synthesis` | Deterministic and mocked LLM synthesis policy | `CODE/RAG` | Yes |
| `simulation` | Replay fixture, API, readiness, and live-unavailable behavior | `CODE/Simulation` | Yes |
| `repository_hygiene` | Submission hygiene validator | `.` | Yes |
| `artifact_integrity` | Fixture/corpus/deployment artifact integrity | `.` | Yes |
| `static_configuration` | JSON/YAML/script/compile/secret/static checks | `.` | Yes |
| `optional_smoke` | Host smoke against an already running Compose stack | `.` | No |

## Modes

Default mode runs all required offline/static suites and does not start the production stack.

Fast mode runs the component and root suites marked `fast`.

Static-only mode runs hygiene, artifact integrity, and static configuration suites.

Smoke mode adds `scripts/smoke_test.py`, but only after checking that the root Compose stack is already running and healthy. It does not call `docker compose up`.

## Local And Docker

Local mode uses the first valid interpreter in this order: `--python`, `TEST_PYTHON`, the current interpreter, repository virtualenv candidates, then platform Python commands. It verifies Python, pytest, and minimal packages before running.

When local Python is unavailable, the wrappers build `Dockerfile.test` and run the matrix inside `telcomind/test-runner:batch8`. Host-side orchestrator Docker mode also supports one container per suite. Offline Docker execution uses `--network none`.

## Outputs

The default output directory is `test-results/`, which is ignored by Git.

Files produced:

- `test-results/summary.json`
- `test-results/summary.txt`
- `test-results/logs/<suite>.log`
- `test-results/junit/<suite>.xml`

Required suite failures, unavailable required suites, and timeouts return nonzero. Skipped platform checks are reported in JUnit as skipped, not passed.

## Offline Network Policy

Required offline suites set invalid proxy variables for local execution. Docker fallback runs offline suites with `--network none`. Mocked `fastapi.testclient` and in-process HTTP clients still work because they do not require external DNS or network access.

## Limitations

Passing the offline matrix does not prove live Simu5G execution, full semantic RAG ingestion, real vLLM/model serving, external API behavior, GPU behavior, or clean-machine timing. Those remain later-batch validation topics.

## Troubleshooting

- No Python: install Python with pytest dependencies or use Docker fallback.
- Missing pytest: install `requirements.test.txt` in a local virtualenv or let Docker fallback run.
- Docker daemon unavailable: start Docker Desktop or use a valid local Python environment.
- WSL path issues: run `./test.sh` from WSL with the repository mounted consistently.
- Import collision: run component suites through the root matrix instead of one root pytest command.
- Stale production stack: use `.\deploy.ps1 -Status` or `./deploy.sh --status`; smoke mode requires healthy existing services.

CI-ready command for Batch 11:

```bash
./test.sh --execution-mode docker
```
