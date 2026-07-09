#!/bin/bash
# JoySafeter Backend entrypoint (JDOS)
# 由容器运行时环境变量驱动，在 admin 用户下由 ENTRYPOINT 调用。
#
# 环境变量:
#   JOYSAFETER_SERVICE_ROLE  api | worker | all (默认 all)
#   BACKEND_PORT             监听端口 (默认 8000)
#   WORKERS                  gunicorn worker 数 (默认 1)
#   BACKEND_APP_MODULE       覆盖 ASGI app 模块 (高级用法)

set -e

export PATH="/export/App/backend/.venv/bin:$PATH"
export PYTHONPATH="/export/App/backend/.venv/lib/python3.12/site-packages:/export/App/backend"

SERVICE_ROLE="${JOYSAFETER_SERVICE_ROLE:-all}"
PORT="${BACKEND_PORT:-8000}"
NUM_WORKERS="${WORKERS:-1}"

# 按角色选择 ASGI app 模块
case "${SERVICE_ROLE}" in
  api)    DEFAULT_MODULE="app.joysafeter_api.main:app" ;;
  worker) DEFAULT_MODULE="app.joysafeter_worker.main:app" ;;
  *)      DEFAULT_MODULE="app.main:app" ;;
esac
APP_MODULE="${BACKEND_APP_MODULE:-$DEFAULT_MODULE}"

cd /export/App/backend

echo "Starting JoySafeter backend: role=${SERVICE_ROLE} module=${APP_MODULE} port=${PORT} workers=${NUM_WORKERS}"

exec python -m gunicorn \
  "${APP_MODULE}" \
  -w "${NUM_WORKERS}" \
  -k uvicorn.workers.UvicornWorker \
  --bind "0.0.0.0:${PORT}" \
  --timeout 120 \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile -
