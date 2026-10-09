#!/usr/bin/env bash
# CI-only: uses a unique project/volume; never reuses the local dev stack.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export COMPOSE_PROJECT_NAME="finagent-ci-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$$"
export CI_ARTIFACT_DIR="${CI_ARTIFACT_DIR:-$ROOT/artifacts/docker-ci}"
export LLM_API_KEY='' BENCHMARK_IMPORT_TOKEN='' SEC_USER_AGENT=''
export POSTGRES_PASSWORD=ci_ephemeral_only
export FINAGENT_LANGFUSE_ENABLED=false LANGFUSE_PUBLIC_KEY='' LANGFUSE_SECRET_KEY=''
mkdir -p "$CI_ARTIFACT_DIR"
compose=(docker compose -f "$ROOT/compose.yaml")
finish() {
  local status=$? cleanup_status
  trap - EXIT
  set +e
  "${compose[@]}" ps --all --format json > "$CI_ARTIFACT_DIR/compose-ps.json" 2>&1
  "${compose[@]}" logs --no-color --timestamps > "$CI_ARTIFACT_DIR/compose.log" 2>&1
  "${compose[@]}" down --volumes --remove-orphans > "$CI_ARTIFACT_DIR/cleanup.log" 2>&1
  cleanup_status=$?
  if [[ $status -eq 0 && $cleanup_status -ne 0 ]]; then status=$cleanup_status; fi
  if [[ $status -ne 0 ]]; then
    echo "Docker CI FAILED (exit $status); container logs follow:"
    cat "$CI_ARTIFACT_DIR/compose.log"
    cat "$CI_ARTIFACT_DIR/cleanup.log"
  fi
  exit "$status"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# No optional/fallback success path when Docker or a required check is missing.
docker version
docker compose version
"${compose[@]}" config --quiet
"${compose[@]}" --progress plain build api worker frontend
"${compose[@]}" up -d --wait --wait-timeout 180
"${compose[@]}" exec -T postgres pg_isready -U finagent -d finagent
python3 scripts/ci/compose_smoke.py --report "$CI_ARTIFACT_DIR/integration.json"
