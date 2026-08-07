#!/bin/bash
# =============================================================================
# 创建 JoySafeter Secrets (部署前执行一次)
# =============================================================================
#
# 用法:
#   ./create-secrets.sh                              # 交互式输入
#   ./create-secrets.sh --from-env                   # 从环境变量读取
#   ./create-secrets.sh --from-file .env.production  # 从文件读取
# =============================================================================

set -euo pipefail

NAMESPACE="joysafeter"

# 检查是否从环境变量或文件读取
FROM_ENV=""
FROM_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --from-env)  FROM_ENV="true"; shift ;;
    --from-file) FROM_FILE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# 从文件加载
if [[ -n "${FROM_FILE}" ]]; then
  if [[ ! -f "${FROM_FILE}" ]]; then
    echo "❌ File not found: ${FROM_FILE}"
    exit 1
  fi
  set -a
  source "${FROM_FILE}"
  set +a
  FROM_ENV="true"
fi

if [[ "${FROM_ENV}" == "true" ]]; then
  DB_URL="${DATABASE_URL:-}"
  REDIS="${REDIS_URL:-}"
  VAULT_KEY="${JOYSAFETER_VAULT_ENCRYPTION_KEY:-}"
else
  echo "═══════════════════════════════════════════════════════════════"
  echo "  JoySafeter Secrets Configuration"
  echo "═══════════════════════════════════════════════════════════════"
  echo ""

  read -p "DATABASE_URL (postgresql+asyncpg://user:pass@host:5432/db): " DB_URL
  read -p "REDIS_URL (redis://:pass@host:6379/0): " REDIS
  read -p "VAULT_ENCRYPTION_KEY (base64, 生成: openssl rand -base64 32): " VAULT_KEY
fi

# 验证
if [[ -z "${DB_URL}" || -z "${REDIS}" || -z "${VAULT_KEY}" ]]; then
  echo "❌ All fields are required"
  exit 1
fi

# 创建 namespace (如果不存在)
kubectl create namespace "${NAMESPACE}" 2>/dev/null || true

# 删除旧 secret (如果存在)
kubectl delete secret joysafeter-secrets -n "${NAMESPACE}" 2>/dev/null || true

# 创建
kubectl create secret generic joysafeter-secrets -n "${NAMESPACE}" \
  --from-literal=DATABASE_URL="${DB_URL}" \
  --from-literal=REDIS_URL="${REDIS}" \
  --from-literal=JOYSAFETER_VAULT_ENCRYPTION_KEY="${VAULT_KEY}"

echo ""
echo "✅ Secret 'joysafeter-secrets' created in namespace '${NAMESPACE}'"
