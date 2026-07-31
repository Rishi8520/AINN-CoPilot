#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-telcomind-quickstart}"
SERVICES=(simulation rag agent gateway ui)
STARTED_AT="$(date +%s)"

log() {
  printf '[%s] %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

usage() {
  printf 'Usage: %s [--status|--logs|--down|--verify]\n' "$0"
}

compose() {
  docker compose --project-directory "$ROOT" --project-name "$PROJECT_NAME" "$@"
}

require_docker() {
  command -v docker >/dev/null 2>&1 || { log "Docker CLI is not installed."; exit 1; }
  docker version >/dev/null
  docker compose version >/dev/null
  log "Docker: $(docker version --format '{{.Client.Version}}')"
  log "Compose: $(docker compose version --short)"
}

required_files() {
  local files=(
    "$ROOT/docker-compose.yml"
    "$ROOT/CODE/Simulation/Dockerfile.quickstart"
    "$ROOT/CODE/RAG/Dockerfile.quickstart"
    "$ROOT/CODE/Agent/Dockerfile.quickstart"
    "$ROOT/CODE/Agent/ui/Dockerfile.quickstart"
    "$ROOT/scripts/smoke_test.py"
  )
  for file in "${files[@]}"; do
    [[ -f "$file" ]] || { log "Required file is missing: $file"; exit 1; }
  done
}

check_ports() {
  local ports=("${HOST_SIMULATION_PORT:-7000}" "${HOST_RAG_PORT:-7001}" "${HOST_AGENT_PORT:-9090}" "${HOST_GATEWAY_PORT:-8888}" "${HOST_UI_PORT:-8501}")
  if command -v python3 >/dev/null 2>&1; then
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
  if command -v python3 >/dev/null 2>&1; then
    python3 "$ROOT/scripts/smoke_test.py"
  elif command -v python >/dev/null 2>&1; then
    python "$ROOT/scripts/smoke_test.py"
  else
    log "Host Python is unavailable; running smoke test in a disposable Python container."
    docker run --rm \
      --add-host=host.docker.internal:host-gateway \
      -v "$ROOT/scripts/smoke_test.py:/smoke_test.py:ro" \
      python:3.11.10-slim-bookworm \
      python /smoke_test.py \
      --simulation-url "http://host.docker.internal:${HOST_SIMULATION_PORT:-7000}" \
      --rag-url "http://host.docker.internal:${HOST_RAG_PORT:-7001}" \
      --agent-url "http://host.docker.internal:${HOST_AGENT_PORT:-9090}" \
      --gateway-url "http://host.docker.internal:${HOST_GATEWAY_PORT:-8888}" \
      --ui-url "http://host.docker.internal:${HOST_UI_PORT:-8501}"
  fi
}

print_urls() {
  cat <<EOF
Simulation: http://localhost:${HOST_SIMULATION_PORT:-7000}
RAG:        http://localhost:${HOST_RAG_PORT:-7001}
Agent:      http://localhost:${HOST_AGENT_PORT:-9090}
Gateway:    http://localhost:${HOST_GATEWAY_PORT:-8888}
UI:         http://localhost:${HOST_UI_PORT:-8501}
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
    check_ports
    if [[ -f "$ROOT/.env" ]]; then
      log "Using existing .env without modifying it."
    else
      log "No .env found; using docker-compose.yml defaults."
    fi
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
