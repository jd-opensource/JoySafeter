#!/bin/bash
# =============================================================================
# 验证 JoySafeter 部署健康状态
# =============================================================================
#
# 用法:
#   ./verify.sh
# =============================================================================

set -euo pipefail

NAMESPACE="joysafeter"
ERRORS=0

echo "═══════════════════════════════════════════════════════════════"
echo "  JoySafeter Deployment Verification"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# 1. Orchestrator Pods
echo "── Orchestrator Pods ──"
ORCH_READY=$(kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-orchestrator \
  --field-selector=status.phase=Running -o name 2>/dev/null | wc -l)
ORCH_TOTAL=$(kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-orchestrator \
  -o name 2>/dev/null | wc -l)
echo "  Running: ${ORCH_READY}/${ORCH_TOTAL}"
if [[ "${ORCH_READY}" -eq 0 ]]; then
  echo "  ❌ No orchestrator pods running!"
  ERRORS=$((ERRORS + 1))
else
  echo "  ✅ OK"
fi
echo ""

# 2. Envoy DaemonSet
echo "── Envoy DaemonSet ──"
ENVOY_READY=$(kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-envoy \
  --field-selector=status.phase=Running -o name 2>/dev/null | wc -l)
ENVOY_DESIRED=$(kubectl get daemonset joysafeter-envoy -n "${NAMESPACE}" \
  -o jsonpath='{.status.desiredNumberScheduled}' 2>/dev/null || echo "0")
echo "  Running: ${ENVOY_READY}/${ENVOY_DESIRED}"
if [[ "${ENVOY_READY}" -eq 0 ]]; then
  echo "  ❌ No envoy pods running!"
  ERRORS=$((ERRORS + 1))
else
  echo "  ✅ OK"
fi
echo ""

# 3. Health Check
echo "── Health Checks ──"
for pod in $(kubectl get pods -n "${NAMESPACE}" -l app=joysafeter-orchestrator \
  --field-selector=status.phase=Running -o name 2>/dev/null); do
  POD_NAME=$(echo "${pod}" | cut -d'/' -f2)
  HEALTH=$(kubectl exec -n "${NAMESPACE}" "${POD_NAME}" -- \
    sh -c "wget -qO- http://localhost:9091/healthz/ready 2>/dev/null" || echo "FAIL")
  echo "  ${POD_NAME}: ${HEALTH}"
done
echo ""

# 4. HA Mode
echo "── HA Mode ──"
HA_MODE=$(kubectl get deployment joysafeter-orchestrator -n "${NAMESPACE}" \
  -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="JOYSAFETER_HA_MODE")].value}' 2>/dev/null)
echo "  Mode: ${HA_MODE:-unknown}"
echo ""

# 5. Logs (last errors)
echo "── Recent Errors (last 5 min) ──"
ERROR_COUNT=$(kubectl logs -n "${NAMESPACE}" -l app=joysafeter-orchestrator \
  --since=5m 2>/dev/null | grep -ci "error" || echo "0")
echo "  Error lines: ${ERROR_COUNT}"
if [[ "${ERROR_COUNT}" -gt 10 ]]; then
  echo "  ⚠️  High error rate!"
  ERRORS=$((ERRORS + 1))
fi
echo ""

# Summary
echo "═══════════════════════════════════════════════════════════════"
if [[ "${ERRORS}" -eq 0 ]]; then
  echo "  ✅ All checks passed"
else
  echo "  ❌ ${ERRORS} check(s) failed"
  exit 1
fi
