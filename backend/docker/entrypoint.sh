#!/bin/bash
# JoySafeter Backend entrypoint (JDOS)
# 参照 Dify entrypoint 模式:所有默认值兜底在此脚本处理,ENTRYPOINT 只透传变量。
#
# 环境变量:
#   MODE                     api | worker | all | migration (默认 all)
#   JOYSAFETER_SERVICE_ROLE  等价于 MODE (MODE 优先);由 app 内部读取
#   BACKEND_PORT             监听端口 (默认 8000)
#   WORKERS                  gunicorn worker 数 (默认 1)
#   BACKEND_APP_MODULE       覆盖 ASGI app 模块 (高级用法)
#   MIGRATION_ENABLED        true 时启动前执行 alembic 数据库迁移
#   DEBUG                    true 时 uvicorn --reload 单进程调试

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
# MODE 与 JOYSAFETER_SERVICE_ROLE 互为别名,MODE 优先
export MODE="${MODE:-${JOYSAFETER_SERVICE_ROLE:-all}}"
export JOYSAFETER_SERVICE_ROLE="${MODE}"
export BACKEND_PORT="${BACKEND_PORT:-8000}"
export WORKERS="${WORKERS:-1}"

# ---------------------------------------------------------------------------
# 数据库迁移 (可选)
# ---------------------------------------------------------------------------
if [[ "${MIGRATION_ENABLED}" == "true" ]]; then
  echo "Running database migrations (alembic upgrade head)"
  alembic upgrade head
  # 纯迁移模式: 迁移完就退出,不启动服务
  if [[ "${MODE}" == "migration" ]]; then
    echo "Migration completed, exiting normally"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# 按 MODE 选择 ASGI app 模块
# ---------------------------------------------------------------------------
case "${MODE}" in
  api)    DEFAULT_MODULE="app.joysafeter_api.main:app" ;;
  worker) DEFAULT_MODULE="app.joysafeter_worker.main:app" ;;
  *)      DEFAULT_MODULE="app.main:app" ;;
esac
APP_MODULE="${BACKEND_APP_MODULE:-$DEFAULT_MODULE}"

echo "Starting JoySafeter backend: mode=${MODE} module=${APP_MODULE} port=${BACKEND_PORT} workers=${WORKERS}"

# ---------------------------------------------------------------------------
# 启动服务
# ---------------------------------------------------------------------------
if [[ "${DEBUG}" == "true" ]]; then
  exec python -m uvicorn "${APP_MODULE}" \
    --host 0.0.0.0 --port "${BACKEND_PORT}" --reload
else
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
fi
