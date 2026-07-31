#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${TEST_DOCKER_IMAGE:-telcomind/test-runner:batch8}"
ARGS=()
CONTAINER_ARGS=()
WITH_E2E=0

while (($#)); do
  case "$1" in
    --fast|--with-smoke|--static-only|--list)
      ARGS+=("$1")
      ;;
    --with-e2e)
      WITH_E2E=1
      ;;
    --execution-mode|--output-dir|--python|--docker-image)
      ARGS+=("$1" "$2")
      shift
      ;;
    *)
      ARGS+=("$1")
      ;;
  esac
  shift
done

stack_is_healthy() {
  command -v docker >/dev/null 2>&1 || return 1
  local rows
  rows="$(docker compose --project-directory "$ROOT" ps --format json 2>/dev/null || true)"
  [[ -n "$rows" ]] || return 1
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    if [[ "$line" != *'"State":"running"'* ]]; then
      return 1
    fi
    if [[ "$line" == *'"Health":"'* ]] && [[ "$line" != *'"Health":"healthy"'* ]]; then
      return 1
    fi
  done <<< "$rows"
  return 0
}

run_demo_e2e() {
  local python_bin="$1"
  if ! stack_is_healthy; then
    printf 'test.sh --with-e2e requires an already running healthy stack. It will not start the stack.\n' >&2
    return 2
  fi
  if [[ -n "$python_bin" ]]; then
    "$python_bin" "$ROOT/scripts/run_demo_scenarios.py" --output-dir e2e-results
    return $?
  fi
  command -v docker >/dev/null 2>&1 || { printf 'test.sh --with-e2e requires local Python or Docker.\n' >&2; return 2; }
  mkdir -p "$ROOT/e2e-results"
  docker run --rm \
    --add-host=host.docker.internal:host-gateway \
    -v "$ROOT:/repo:ro" \
    -v "$ROOT/e2e-results:/e2e-results" \
    -w /repo \
    python:3.11.10-slim-bookworm \
    python scripts/run_demo_scenarios.py --base-url http://host.docker.internal:8888 --output-dir /e2e-results
}

skip_next=0
for ((i = 0; i < ${#ARGS[@]}; i++)); do
  if ((skip_next)); then
    skip_next=0
    continue
  fi
  case "${ARGS[$i]}" in
    --execution-mode)
      skip_next=1
      ;;
    --output-dir)
      skip_next=1
      ;;
    --python)
      skip_next=1
      ;;
    --docker-image)
      skip_next=1
      ;;
    *)
      CONTAINER_ARGS+=("${ARGS[$i]}")
      ;;
  esac
done

cd "$ROOT"

PYTHON_BIN="${TEST_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python)"
  fi
fi

if [[ -n "$PYTHON_BIN" ]] && "$PYTHON_BIN" -m pytest --version >/dev/null 2>&1; then
  printf 'test.sh: using local Python: %s\n' "$PYTHON_BIN"
  "$PYTHON_BIN" "$ROOT/scripts/run_test_matrix.py" "${ARGS[@]}"
  rc=$?
  if (( rc != 0 || WITH_E2E == 0 )); then
    exit $rc
  fi
  run_demo_e2e "$PYTHON_BIN"
  exit $?
fi

if ! command -v docker >/dev/null 2>&1; then
  printf 'test.sh: no usable local Python and Docker is unavailable.\n' >&2
  exit 2
fi

printf 'test.sh: using Docker fallback image: %s\n' "$IMAGE"
docker build -f Dockerfile.test -t "$IMAGE" "$ROOT"
mkdir -p "$ROOT/test-results"
docker run --rm --network none \
  -v "$ROOT:/repo:ro" \
  -v "$ROOT/test-results:/test-results" \
  -w /repo \
  "$IMAGE" \
  python scripts/run_test_matrix.py --execution-mode local --output-dir /test-results "${CONTAINER_ARGS[@]}"
rc=$?
if (( rc != 0 || WITH_E2E == 0 )); then
  exit $rc
fi
run_demo_e2e ""
exit $?
