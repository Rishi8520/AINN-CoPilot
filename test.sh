#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE="${TEST_DOCKER_IMAGE:-telcomind/test-runner:batch8}"
ARGS=()
CONTAINER_ARGS=()

while (($#)); do
  case "$1" in
    --fast|--with-smoke|--static-only|--list)
      ARGS+=("$1")
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
