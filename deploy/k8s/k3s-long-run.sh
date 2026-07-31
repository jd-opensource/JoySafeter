#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
SANDBOX_NS="${JOYSAFETER_K8S_NAMESPACE:-joysafeter-sandboxes}"
DURATION_SECONDS="${DURATION_SECONDS:-21600}"
INTERVAL_SECONDS="${INTERVAL_SECONDS:-300}"
MAX_RUNS="${MAX_RUNS:-0}"
FAIL_FAST="${FAIL_FAST:-false}"
RUN_PREFIX="${RUN_PREFIX:-$(date +%Y%m%d%H%M%S)}"
LOG_DIR="${LOG_DIR:-/tmp/joysafeter-k3s-long-run-${RUN_PREFIX}}"
VALIDATION_MODE="${VALIDATION_MODE:-task}"

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m⚠ %s\033[0m\n' "$*" >&2; }

mkdir -p "$LOG_DIR"

run_observation() {
  local iter="$1"
  local outfile="$LOG_DIR/observe-${iter}.log"
  {
    echo "== $(date -Iseconds) control pods =="
    "$KUBECTL" -n "$CONTROL_NS" get pods -o wide
    echo
    echo "== $(date -Iseconds) sandbox pods =="
    "$KUBECTL" -n "$SANDBOX_NS" get pods -o wide
    echo
    echo "== $(date -Iseconds) api health =="
    curl -sS "${API_URL:-http://127.0.0.1:8000}/api/v1/health" || true
    echo
  } >"$outfile" 2>&1
}

main() {
  local started_at now deadline iter passed failed
  started_at="$(date +%s)"
  deadline=$((started_at + DURATION_SECONDS))
  iter=0
  passed=0
  failed=0

  log "Long-run validation started"
  echo "Log dir:          $LOG_DIR"
  echo "Duration seconds: $DURATION_SECONDS"
  echo "Interval seconds: $INTERVAL_SECONDS"
  echo "Max runs:         $MAX_RUNS"
  echo "Fail fast:        $FAIL_FAST"
  echo "Validation mode:  $VALIDATION_MODE"
  echo ""
  echo "This script preserves all validation data. It does not delete users, agents, tasks, pods, jobs, namespaces, PVCs, or database rows."
  echo ""

  while true; do
    now="$(date +%s)"
    if (( now >= deadline )); then
      break
    fi
    if (( MAX_RUNS > 0 && iter >= MAX_RUNS )); then
      break
    fi

    iter=$((iter + 1))
    local run_id run_log
    run_id="${RUN_PREFIX}-${iter}"
    run_log="$LOG_DIR/task-smoke-${iter}.log"

    log "Run ${iter}: RUN_ID=${run_id}"
    local smoke_script
    case "$VALIDATION_MODE" in
      task)
        smoke_script="$SCRIPT_DIR/k3s-task-smoke.sh"
        ;;
      egress)
        smoke_script="$SCRIPT_DIR/k3s-egress-smoke.sh"
        ;;
      *)
        echo "Unsupported VALIDATION_MODE: $VALIDATION_MODE (expected task or egress)" >&2
        exit 1
        ;;
    esac

    if RUN_ID="$run_id" "$smoke_script" >"$run_log" 2>&1; then
      passed=$((passed + 1))
      ok "Run ${iter} passed"
    else
      failed=$((failed + 1))
      warn "Run ${iter} failed; see $run_log"
      if [[ "$FAIL_FAST" == "true" ]]; then
        run_observation "$iter"
        exit 1
      fi
    fi

    run_observation "$iter"

    now="$(date +%s)"
    if (( now >= deadline )); then
      break
    fi
    if (( MAX_RUNS > 0 && iter >= MAX_RUNS )); then
      break
    fi
    sleep "$INTERVAL_SECONDS"
  done

  echo ""
  echo "Runs:   $iter"
  echo "Passed: $passed"
  echo "Failed: $failed"
  echo "Logs:   $LOG_DIR"

  if (( failed > 0 )); then
    exit 1
  fi
}

main "$@"
