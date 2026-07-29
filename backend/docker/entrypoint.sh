#!/bin/bash
# JoySafeter Backend entrypoint (JDOS)
# 所有默认值兜底在此脚本处理,ENTRYPOINT 只透传变量。
#
# 环境变量:
#   JOYSAFETER_SERVICE_ROLE  api | worker | all (默认 all)
#   BACKEND_PORT             监听端口 (默认 8000)
#   WORKERS                  gunicorn worker 数 (默认 1)
#   BACKEND_APP_MODULE       覆盖 ASGI app 模块 (高级用法)
#   MIGRATION_ENABLED        true 时启动前执行 alembic 数据库迁移

set -e

# UTF-8 编码 (规避容器环境编码问题),C.UTF-8 所有容器通用
export LANG=${LANG:-C.UTF-8}
export LC_ALL=${LC_ALL:-C.UTF-8}
export PYTHONIOENCODING=${PYTHONIOENCODING:-utf-8}

export PATH="/export/App/backend/.venv/bin:$PATH"
export PYTHONPATH="/export/App/backend/.venv/lib/python3.12/site-packages:/export/App/backend"

cd /export/App/backend

# ---------------------------------------------------------------------------
# 归一化环境变量并 re-export
#
# 关键: JDOS 对未配置的变量会注入空字符串 "",而 pydantic Settings 无法把
# "" 解析成 int。这里用 :- 兜默认值后 re-export,确保 os.environ 里拿到的
# 是合法值,而不是空串。
# ---------------------------------------------------------------------------
export JOYSAFETER_SERVICE_ROLE="${JOYSAFETER_SERVICE_ROLE:-all}"
export BACKEND_PORT="${BACKEND_PORT:-8000}"
export WORKERS="${WORKERS:-1}"

# ---------------------------------------------------------------------------
# 数据库迁移 (可选)
# ---------------------------------------------------------------------------
if [[ "${MIGRATION_ENABLED}" == "true" ]]; then
  echo "Running database migrations (alembic upgrade head)"
  alembic upgrade head
fi

# ---------------------------------------------------------------------------
# 按服务角色选择 ASGI app 模块
# ---------------------------------------------------------------------------
case "${JOYSAFETER_SERVICE_ROLE}" in
  api)    DEFAULT_MODULE="app.joysafeter_api.main:app" ;;
  worker) DEFAULT_MODULE="app.joysafeter_worker.main:app" ;;
  *)      DEFAULT_MODULE="app.main:app" ;;
esac
APP_MODULE="${BACKEND_APP_MODULE:-$DEFAULT_MODULE}"

echo "Starting JoySafeter backend: role=${JOYSAFETER_SERVICE_ROLE} module=${APP_MODULE} port=${BACKEND_PORT} workers=${WORKERS}"

# ---------------------------------------------------------------------------
# 启动服务
# ---------------------------------------------------------------------------
exec python -m gunicorn \
  "${APP_MODULE}" \
  -w "${WORKERS}" \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${BACKEND_PORT}" \
  --timeout "${GUNICORN_TIMEOUT:-120}" \
  --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
  --max-requests "${GUNICORN_MAX_REQUESTS:-5000}" \
  --max-requests-jitter "${GUNICORN_MAX_REQUESTS_JITTER:-500}" \
  --access-logfile - \
  --error-logfile -
