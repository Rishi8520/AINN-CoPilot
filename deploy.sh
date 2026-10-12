#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_ARGS=()
ENV_FILE=""
if [[ -f "$ROOT/.env" ]]; then
  ENV_FILE="$ROOT/.env"
elif [[ -f "$ROOT/CODE/.env" ]]; then
  ENV_FILE="$ROOT/CODE/.env"
fi
[[ -z "$ENV_FILE" ]] || ENV_ARGS=(--env-file "$ENV_FILE")
SERVICES=(simulation rag agent gateway ui)
STARTED_AT="$(date +%s)"
COMPOSE_FILES=(-f "$ROOT/docker-compose.yml" -f "$ROOT/docker-compose.live.yml")
DEPLOY_MODE=live
if [[ "${1:-}" == "--replay" ]]; then
  COMPOSE_FILES=(-f "$ROOT/docker-compose.yml")
  DEPLOY_MODE=replay
  shift
fi
if [[ "${1:-}" == "--opea" ]]; then
  [[ "$DEPLOY_MODE" == live ]] || { printf 'OPEA deployment verification requires the live profile. Select replay per query in the UI.\n'; exit 2; }
  COMPOSE_FILES+=(-f "$ROOT/docker-compose.opea.yml")
  SERVICES=(opea-reasoner "${SERVICES[@]}")
  shift
fi

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

usage() {
  printf 'Usage: %s [--replay] [--opea] [--status|--logs|--down|--verify]\n' "$0"
}

compose() {
  docker compose --project-directory "$ROOT" "${ENV_ARGS[@]}" "${COMPOSE_FILES[@]}" "$@"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || { log "Docker CLI is not installed."; exit 1; }
  docker version >/dev/null
  docker compose version >/dev/null
  log "Docker: $(docker version --format '{{.Client.Version}}')"
  log "Compose: $(docker compose version --short)"
  if [[ -n "$ENV_FILE" ]]; then
    log "Using environment file: ${ENV_FILE#"$ROOT/"}"
  else
    log "No .env or CODE/.env found; using Compose defaults and exported variables."
  fi
  if ! compose config --quiet; then
    log "Compose configuration is invalid. Check the selected environment file and required variables."
    exit 1
  fi
}

required_files() {
  local files=(
    "$ROOT/docker-compose.yml"
    "$ROOT/CODE/Simulation/Dockerfile.quickstart"
    "$ROOT/CODE/RAG/Dockerfile.quickstart"
    "$ROOT/CODE/Agent/Dockerfile.quickstart"
    "$ROOT/CODE/Agent/ui/Dockerfile.quickstart"
    "$ROOT/scripts/smoke_test.py"
    "$ROOT/docker-compose.live.yml"
    "$ROOT/CODE/Simulation/live/service.py"
    "$ROOT/scripts/smoke_live.py"
  )
  for file in "${files[@]}"; do
    [[ -f "$file" ]] || { log "Required file is missing: $file"; exit 1; }
  done
}

check_ports() {
  if [[ -n "$(compose ps -q 2>/dev/null)" ]]; then
    log "Updating the existing project; Docker will retain its port bindings."
    return
  fi
  local ports=("${HOST_SIMULATION_PORT:-7000}" "${HOST_RAG_PORT:-7001}" "${HOST_AGENT_PORT:-9090}" "${HOST_GATEWAY_PORT:-8888}" "${HOST_UI_PORT:-8501}")
  if command -v python3 >/dev/null 2>&1; then
    local config_json port_lines
    config_json="$(compose config --format json)" || return 1
    port_lines="$(python3 -c 'import json,sys; config=json.load(sys.stdin); print("\n".join(str(port["published"]) for name in ("simulation","rag","agent","gateway","ui") for port in config["services"][name]["ports"]))' <<< "$config_json")" || return 1
    mapfile -t ports <<< "$port_lines"
    python3 - "$@" "${ports[@]}" <<'PY'
import socket
import sys
for raw in sys.argv[1:]:
    port = int(raw)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Port {port} appears to be in use before deploy.")
            sys.exit(1)
PY
  elif command -v python >/dev/null 2>&1; then
    python - "$@" "${ports[@]}" <<'PY'
import socket
import sys
for raw in sys.argv[1:]:
    port = int(raw)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            print(f"Port {port} appears to be in use before deploy.")
            sys.exit(1)
PY
  else
    log "Python is unavailable; skipping host port preflight."
  fi
}

health_status() {
  local service="$1"
  local cid
  cid="$(compose ps -q "$service")"
  [[ -n "$cid" ]] || return 1
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$cid"
}

wait_healthy() {
  local deadline=$((SECONDS + ${DEPLOY_HEALTH_TIMEOUT_SECONDS:-180}))
  for service in "${SERVICES[@]}"; do
    log "Waiting for $service health..."
    while (( SECONDS < deadline )); do
      status="$(health_status "$service" 2>/dev/null || true)"
      [[ "$status" == "healthy" ]] && { log "$service is healthy."; break; }
      sleep 3
    done
    status="$(health_status "$service" 2>/dev/null || true)"
    if [[ "$status" != "healthy" ]]; then
      log "$service did not become healthy; status=${status:-missing}"
      compose logs --tail=120 "$service" || true
      exit 1
    fi
  done
}

run_smoke() {
  local smoke="$ROOT/scripts/smoke_test.py"
  [[ "$DEPLOY_MODE" == live ]] && smoke="$ROOT/scripts/smoke_live.py"
  if command -v python3 >/dev/null 2>&1; then
    python3 "$smoke" \
      --simulation-url "http://localhost:$(host_port simulation 7000)" \
      --rag-url "http://localhost:$(host_port rag 7001)" \
      --agent-url "http://localhost:$(host_port agent 9090)" \
      --gateway-url "http://localhost:$(host_port gateway 8888)" \
      --ui-url "http://localhost:$(host_port ui 8501)"
  elif command -v python >/dev/null 2>&1; then
    python "$smoke" \
      --simulation-url "http://localhost:$(host_port simulation 7000)" \
      --rag-url "http://localhost:$(host_port rag 7001)" \
      --agent-url "http://localhost:$(host_port agent 9090)" \
      --gateway-url "http://localhost:$(host_port gateway 8888)" \
      --ui-url "http://localhost:$(host_port ui 8501)"
  else
    log "Host Python is unavailable; running smoke test in a disposable Python container."
    docker run --rm \
      --add-host=host.docker.internal:host-gateway \
      -v "$smoke:/smoke_test.py:ro" \
      python:3.11.10-slim-bookworm \
      python /smoke_test.py \
      --simulation-url "http://host.docker.internal:$(host_port simulation 7000)" \
      --rag-url "http://host.docker.internal:$(host_port rag 7001)" \
      --agent-url "http://host.docker.internal:$(host_port agent 9090)" \
      --gateway-url "http://host.docker.internal:$(host_port gateway 8888)" \
      --ui-url "http://host.docker.internal:$(host_port ui 8501)"
  fi
}

host_port() {
  compose port "$1" "$2" | tail -1 | awk -F: '{print $NF}'
}

print_urls() {
  cat <<EOF
Simulation: http://localhost:$(host_port simulation 7000)
RAG:        http://localhost:$(host_port rag 7001)
Agent:      http://localhost:$(host_port agent 9090)
Gateway:    http://localhost:$(host_port gateway 8888)
UI:         http://localhost:$(host_port ui 8501)
EOF
}

mode="${1:-deploy}"
case "$mode" in
  --status)
    require_docker
    compose ps
    ;;
  --logs)
    require_docker
    compose logs --tail=200
    ;;
  --down)
    require_docker
    compose down
    ;;
  --verify)
    require_docker
    wait_healthy
    run_smoke
    ;;
  deploy)
    cd "$ROOT"
    require_docker
    required_files
    log "Deployment mode: $DEPLOY_MODE"
    check_ports
    compose up -d --build
    wait_healthy
    compose ps
    run_smoke
    print_urls
    duration=$(($(date +%s) - STARTED_AT))
    log "Deployment verified in ${duration}s."
    ;;
  *)
    usage
    exit 2
    ;;
esac
