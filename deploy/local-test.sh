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

  log "等待 PostgreSQL 就绪"
  local ready=false
  for _ in $(seq 1 60); do
    if compose -f docker-compose.yml exec -T db \
        pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-joysafeter}" >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 1
  done
  if [ "$ready" != true ]; then
    echo "PostgreSQL 在 60s 内未就绪；请检查 docker compose logs db" >&2
    exit 1
  fi

  # 用宿主机源码跑迁移，而不是容器 db-init 镜像。api/worker/orchestrator 都从宿主机
  # 源码启动，迁移也应如此：容器 db-init 可能是陈旧的 joysafeter-backend:latest，
  # 会把库迁到旧 head，而宿主机源码期待更新的表，造成崩溃。宿主机 alembic 让 schema
  # 与代码始终一致，也不必为跑一次迁移去构建整个 backend 镜像。
  log "运行数据库迁移（宿主机源码 alembic upgrade head）"
  ( cd "$ROOT/backend" && uv run alembic upgrade head )
}

start_backend() {
  cd "$ROOT/backend"
  export JOYSAFETER_EVENT_STREAM_ENABLED=true
  export JOYSAFETER_GRPC_PUBLIC_URL="${JOYSAFETER_GRPC_PUBLIC_URL:-http://host.docker.internal:9090}"

  log "启动 API :8000"
  JOYSAFETER_SERVICE_ROLE=api uv run uvicorn app.joysafeter_api.main:app --host 0.0.0.0 --port 8000 &
  PIDS+=("$!")

  log "启动 Rust Orchestrator gRPC :9090"
  (
    cd "$ROOT/backend/app/joysafeter_orchestrator_rs"
    JOYSAFETER_GRPC_HOST=0.0.0.0 \
      JOYSAFETER_GRPC_PORT="${JOYSAFETER_GRPC_PORT:-9090}" \
      cargo run --release
  ) &
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
  echo "gRPC:     http://host.docker.internal:${JOYSAFETER_GRPC_PORT:-9090}"
  echo "按 Ctrl+C 停止本地进程；PostgreSQL/Redis 可用: cd deploy && docker compose down"
  wait
}

main "$@"
