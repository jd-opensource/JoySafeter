#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KUBECTL="${KUBECTL:-kubectl}"
CONTROL_NS="${JOYSAFETER_CONTROL_NAMESPACE:-joysafeter-control}"
EGRESS_NS="${JOYSAFETER_EGRESS_NAMESPACE:-joysafeter-egress}"
GO_XDS_IMAGE="${GO_XDS_IMAGE:-}"
GO_XDS_REPLICAS="${GO_XDS_REPLICAS:-3}"

"$KUBECTL" -n "$CONTROL_NS" get secret joysafeter-egress-controller-tls >/dev/null || {
  echo "missing joysafeter-egress-controller-tls; provision the legacy Go xDS server certificate before rollback" >&2
  exit 1
}
if ! "$KUBECTL" -n "$CONTROL_NS" get deployment joysafeter-egress-controller >/dev/null 2>&1; then
  if [[ -z "$GO_XDS_IMAGE" ]]; then
    echo "GO_XDS_IMAGE is required when the legacy Go Deployment no longer exists" >&2
    exit 1
  fi
  "$KUBECTL" apply -f "$SCRIPT_DIR/base/25-egress-controller.yaml"
fi
if [[ -n "$GO_XDS_IMAGE" ]]; then
  "$KUBECTL" -n "$CONTROL_NS" set image deployment/joysafeter-egress-controller \
    controller="$GO_XDS_IMAGE"
fi
"$KUBECTL" -n "$CONTROL_NS" scale deployment/joysafeter-egress-controller --replicas="$GO_XDS_REPLICAS"
"$KUBECTL" -n "$CONTROL_NS" rollout status deployment/joysafeter-egress-controller --timeout=300s
"$KUBECTL" -n "$CONTROL_NS" patch configmap joysafeter-config --type merge -p \
  '{"data":{"JOYSAFETER_EGRESS_XDS_SHADOW_RECONCILE":"false"}}'
"$KUBECTL" -n "$EGRESS_NS" patch networkpolicy joysafeter-egress-envoy --type json -p \
  '[{"op":"replace","path":"/spec/egress/1/to/0/podSelector/matchLabels/app.kubernetes.io~1name","value":"joysafeter-egress-controller"}]'
"$KUBECTL" -n "$EGRESS_NS" patch daemonset joysafeter-egress-envoy --type strategic -p \
  '{"spec":{"template":{"metadata":{"annotations":{"joysafeter.io/xds-control-plane":"go-rollback"}},"spec":{"initContainers":[{"name":"render-bootstrap","env":[{"name":"XDS_ADDRESS","value":"joysafeter-egress-controller.joysafeter-control.svc.cluster.local"},{"name":"XDS_SNI","value":"joysafeter-egress-controller.joysafeter-control.svc.cluster.local"}]}]}}}}'
"$KUBECTL" -n "$CONTROL_NS" rollout restart deployment/joysafeter-orchestrator
"$KUBECTL" -n "$EGRESS_NS" rollout restart daemonset/joysafeter-egress-envoy
"$KUBECTL" -n "$CONTROL_NS" rollout status deployment/joysafeter-orchestrator --timeout=300s
"$KUBECTL" -n "$EGRESS_NS" rollout status daemonset/joysafeter-egress-envoy --timeout=300s
