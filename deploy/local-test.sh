#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY="$ROOT/deploy"
PIDS=()

log() { printf '\033[0;36m▶ %s\033[0m\n' "$*"; }
ok() { printf '\033[0;32m✅ %s\033[0m\n' "$*"; }

cleanup() {
  for pid in "${PIDS[@]:-}"; do
    kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT INT TERM

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

init_env() {
  [ -f "$DEPLOY/.env" ] || cp "$DEPLOY/.env.example" "$DEPLOY/.env"
  [ -f "$ROOT/backend/.env" ] || cp "$ROOT/backend/env.example" "$ROOT/backend/.env"
  [ -f "$ROOT/frontend/.env" ] || cp "$ROOT/frontend/env.example" "$ROOT/frontend/.env"
}

start_infra() {
  log "启动 PostgreSQL / Redis"
  cd "$DEPLOY"
  compose -f docker-compose.yml up -d db redis
  log "运行数据库迁移"
  compose -f docker-compose.yml --profile init run --rm db-init
}

start_backend() {
  cd "$ROOT/backend"
  export JOYSAFETER_EVENT_STREAM_ENABLED=true
  export JOYSAFETER_GRPC_PUBLIC_URL="${JOYSAFETER_GRPC_PUBLIC_URL:-http://host.docker.internal:9090}"

  log "启动 API :8000"
  JOYSAFETER_SERVICE_ROLE=api uv run uvicorn app.joysafeter_api.main:app --host 0.0.0.0 --port 8000 &
  PIDS+=("$!")

  log "启动 Orchestrator :8001 / gRPC :9090"
  JOYSAFETER_SERVICE_ROLE=orchestrator uv run uvicorn app.joysafeter_orchestrator.main:app --host 127.0.0.1 --port 8001 &
  PIDS+=("$!")

  log "启动 Worker :8002"
  JOYSAFETER_SERVICE_ROLE=worker uv run uvicorn app.joysafeter_worker.main:app --host 127.0.0.1 --port 8002 &
  PIDS+=("$!")
}

start_frontend() {
  cd "$ROOT/frontend"
  export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:8000}"
  log "启动 Frontend :3000"
  bun run dev &
  PIDS+=("$!")
}

main() {
  init_env
  start_infra
  start_backend
  start_frontend
  ok "本地测试环境已启动"
  echo "Frontend: http://localhost:3000"
  echo "API:      http://localhost:8000"
  echo "Docs:     http://localhost:8000/docs"
  echo "按 Ctrl+C 停止本地进程；PostgreSQL/Redis 可用: cd deploy && docker compose down"
  wait
}

main "$@"
