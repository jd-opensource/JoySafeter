#!/bin/bash
# =============================================================================
# JoySafeter Orchestrator — Helm 部署脚本
# =============================================================================
#
# 用法:
#   ./deploy.sh                    # 默认部署 (multi 模式, 3 副本)
#   ./deploy.sh --mode leader      # leader 模式 (2 副本, Lease 选主)
#   ./deploy.sh --replicas 5       # 5 副本
#   ./deploy.sh --dry-run          # 只渲染不部署
#   ./deploy.sh --uninstall        # 卸载
#
# 前提:
#   1. kubectl 已配置 (连接目标集群)
#   2. helm v3 已安装
#   3. Secret 已创建 (见下方 create-secrets.sh)
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHART_DIR="${SCRIPT_DIR}/../helm/joysafeter-orchestrator"
RELEASE_NAME="joysafeter-orchestrator"
NAMESPACE="joysafeter"

# 默认值
MODE="multi"
REPLICAS=""
DRY_RUN=""
UNINSTALL=""
VALUES_FILE=""

# 解析参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode)      MODE="$2"; shift 2 ;;
    --replicas)  REPLICAS="$2"; shift 2 ;;
    --dry-run)   DRY_RUN="--dry-run --debug"; shift ;;
    --uninstall) UNINSTALL="true"; shift ;;
    --values|-f) VALUES_FILE="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

# 卸载
if [[ "${UNINSTALL}" == "true" ]]; then
  echo "🗑️  Uninstalling ${RELEASE_NAME}..."
  helm uninstall "${RELEASE_NAME}" -n "${NAMESPACE}" 2>/dev/null || true
  echo "✅ Uninstalled"
  exit 0
fi

# 构建 helm set 参数
SET_ARGS="--set haMode=${MODE}"

if [[ -n "${REPLICAS}" ]]; then
  SET_ARGS="${SET_ARGS} --set orchestrator.replicas=${REPLICAS}"
elif [[ "${MODE}" == "leader" ]]; then
  SET_ARGS="${SET_ARGS} --set orchestrator.replicas=2"
fi

# 检查 Secret 是否存在
if ! kubectl get secret joysafeter-secrets -n "${NAMESPACE}" &>/dev/null; then
  echo "❌ Secret 'joysafeter-secrets' not found in namespace '${NAMESPACE}'"
  echo "   Run: ./create-secrets.sh first"
  exit 1
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  JoySafeter Orchestrator Deployment"
echo "═══════════════════════════════════════════════════════════════"
echo "  Mode:      ${MODE}"
echo "  Replicas:  ${REPLICAS:-default}"
echo "  Namespace: ${NAMESPACE}"
echo "  Chart:     ${CHART_DIR}"
echo "═══════════════════════════════════════════════════════════════"

# 部署
VALUES_ARG=""
if [[ -n "${VALUES_FILE}" ]]; then
  VALUES_ARG="-f ${VALUES_FILE}"
fi

helm upgrade --install "${RELEASE_NAME}" "${CHART_DIR}" \
  --namespace "${NAMESPACE}" \
  --create-namespace \
  ${SET_ARGS} \
  ${VALUES_ARG} \
  ${DRY_RUN}

if [[ -z "${DRY_RUN}" ]]; then
  echo ""
  echo "⏳ Waiting for rollout..."
  kubectl rollout status deployment/joysafeter-orchestrator -n "${NAMESPACE}" --timeout=120s
  echo ""
  echo "✅ Deployment complete!"
  echo ""
  kubectl get pods -n "${NAMESPACE}" -o wide
fi
