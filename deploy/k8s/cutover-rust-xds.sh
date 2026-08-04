#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
EGRESS_NS="${JOYSAFETER_EGRESS_NAMESPACE:-joysafeter-egress}"
STATUS_PORT="${ORCHESTRATOR_HEALTH_PORT_FORWARD_PORT:-18081}"
PORT_FORWARD_PID=""

cleanup() {
  if [[ -n "$PORT_FORWARD_PID" ]]; then
    kill "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
    wait "$PORT_FORWARD_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

command -v curl >/dev/null 2>&1 || {
  echo "curl is required" >&2
  exit 1
}

"$KUBECTL" -n "$CONTROL_NS" patch configmap joysafeter-config --type merge -p \
  '{"data":{"JOYSAFETER_EGRESS_XDS_BIND":"0.0.0.0:18000","JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE":"true"}}'
"$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-orchestrator
"$KUBECTL" -n "$CONTROL_NS" rollout status deployment/joysafeter-orchestrator --timeout=300s
"$KUBECTL" -n "$EGRESS_NS" patch networkpolicy joysafeter-egress-envoy --type json -p \
  '[{"op":"replace","path":"/spec/egress/1/to/0/podSelector/matchLabels/app.kubernetes.io~1name","value":"joysafeter-orchestrator"}]'
"$KUBECTL" -n "$EGRESS_NS" patch daemonset joysafeter-egress-envoy --type strategic -p \
  '{"spec":{"template":{"spec":{"initContainers":[{"name":"render-bootstrap","env":[{"name":"XDS_ADDRESS","value":"joysafeter-orchestrator.joysafeter-control.svc.cluster.local"},{"name":"XDS_SNI","value":"joysafeter-orchestrator.joysafeter-control.svc.cluster.local"}]}]}}}}'
"$KUBECTL" -n "$EGRESS_NS" rollout restart daemonset/joysafeter-egress-envoy
"$KUBECTL" -n "$EGRESS_NS" rollout status daemonset/joysafeter-egress-envoy --timeout=300s

"$KUBECTL" -n "$CONTROL_NS" port-forward service/joysafeter-orchestrator "${STATUS_PORT}:8081" \
  >/tmp/joysafeter-rust-xds-cutover-port-forward.log 2>&1 &
PORT_FORWARD_PID="$!"

for _ in $(seq 1 60); do
  metrics="$(curl -fsS "http://127.0.0.1:${STATUS_PORT}/metrics" 2>/dev/null || true)"
  connected="$(printf '%s\n' "$metrics" | awk '$1 == "joysafeter_rust_xds_connected_nodes" { print $2 }')"
  if [[ -n "$connected" ]] && awk "BEGIN { exit !(${connected} >= 1) }"; then
    break
  fi
  sleep 1
done

metrics="$(curl -fsS "http://127.0.0.1:${STATUS_PORT}/metrics")"
connected="$(printf '%s\n' "$metrics" | awk '$1 == "joysafeter_rust_xds_connected_nodes" { print $2 }')"
if [[ -z "$connected" ]] || ! awk "BEGIN { exit !(${connected} >= 1) }"; then
  echo "cutover aborted: no Envoy node is connected to embedded Rust xDS" >&2
  exit 1
fi
if printf '%s\n' "$metrics" | grep -Eq 'joysafeter_rust_xds_(ack_total\{result="nack"\}|reconcile_total\{result="failed"\}|snapshot_events_total\{result="(rolled_back|timed_out)"\}) [1-9]'; then
  echo "cutover aborted: Rust xDS reported NACK, reconcile failure, rollback, or timeout" >&2
  exit 1
fi

if "$KUBECTL" -n "$CONTROL_NS" get deployment joysafeter-egress-controller >/dev/null 2>&1; then
  "$KUBECTL" -n "$CONTROL_NS" scale deployment/joysafeter-egress-controller --replicas=0
fi

echo "Rust xDS cutover complete; any legacy controller Deployment is scaled to zero."
