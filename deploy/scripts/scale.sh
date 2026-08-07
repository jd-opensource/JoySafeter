#!/bin/bash
# =============================================================================
# 扩缩容 JoySafeter Orchestrator
# =============================================================================
#
# 用法:
#   ./scale.sh 5      # 扩到 5 副本
#   ./scale.sh 1      # 缩到 1 副本
#   ./scale.sh status # 查看当前状态
# =============================================================================

set -euo pipefail

NAMESPACE="joysafeter"
DEPLOYMENT="joysafeter-orchestrator"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <replicas|status>"
  exit 1
fi

if [[ "$1" == "status" ]]; then
  echo "═══════════════════════════════════════════════════════════════"
  echo "  Orchestrator Status"
  echo "═══════════════════════════════════════════════════════════════"
  kubectl get deployment "${DEPLOYMENT}" -n "${NAMESPACE}" -o wide
  echo ""
  kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-orchestrator -o wide
  echo ""
  echo "── Envoy DaemonSet ──"
  kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-envoy -o wide
  exit 0
fi

REPLICAS="$1"

echo "⚙️  Scaling ${DEPLOYMENT} to ${REPLICAS} replicas..."
kubectl scale deployment "${DEPLOYMENT}" -n "${NAMESPACE}" --replicas="${REPLICAS}"

echo "⏳ Waiting for rollout..."
kubectl rollout status deployment/"${DEPLOYMENT}" -n "${NAMESPACE}" --timeout=120s

echo ""
echo "✅ Scaled to ${REPLICAS} replicas"
kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-orchestrator -o wide
