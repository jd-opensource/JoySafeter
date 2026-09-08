#!/usr/bin/env bash
#
# End-to-end HA / stability tests for the standalone JoySafeter Agent Gateway.
#
# Drives a *live* Kubernetes deployment and asserts the high-availability
# invariants that the gateway's leader election, lease fencing, hot-standby
# replication, and xDS delivery must uphold. It intentionally uses only
# kubectl/jq so it can run against any cluster without extra tooling; the
# network/time fault scenarios that kubectl cannot express are provided
# separately in e2e_agent_gateway_chaos.yaml (chaos-mesh).
#
# Usage:
#   NS=joysafeter-pre ./e2e_agent_gateway.sh invariants
#   NS=joysafeter-pre ./e2e_agent_gateway.sh all  # destructive: deletes pods
#   NS=joysafeter-dev ./e2e_agent_gateway.sh failover
#   NS=joysafeter-pre DURATION=120 ./e2e_agent_gateway.sh split-brain-watch
#
# Subcommands:
#   invariants        assert current-state invariants once (single leader, endpoint, epoch)
#   failover          kill the leader, assert clean takeover + fencing epoch advance
#   split-brain-watch poll for DURATION seconds, assert never >1 leader
#   envoy-recovery    kill an Envoy, assert its ADS stream reconnects and re-delivers
#   soak              run failover repeatedly (ITERATIONS), asserting invariants each round
#   all               invariants + failover + envoy-recovery + a short split-brain-watch
#
# Environment:
#   NS               namespace (required)
#   APP_LABEL        gateway pod app label (default: app=joysafeter-agent-gateway)
#   LEADER_LABEL     leader selector label (default: joysafeter-agent-gateway-leader=true)
#   LEASE_NAME       coordination Lease name (default: joysafeter-agent-gateway; dev often -dev)
#   ENVOY_LABEL      envoy pod label (default: app=joysafeter-envoy)
#   SVC              gateway service name (default: joysafeter-agent-gateway)
#   XDS_PORT         xDS port (default: 9092)
#   HTTP_PORT        gateway http/metrics port (default: 9093)
#   LEASE_DURATION   seconds to wait for failover (default: 20)
#   DURATION         split-brain-watch seconds (default: 60)
#   ITERATIONS       soak failover rounds (default: 5)
#   MIN_GATEWAYS     required Gateway replicas (default: 2)
#   MIN_ENVOY_NODES  required distinct Envoy nodes (default: 2)
#   PENDING_TIMEOUT  seconds allowed for xDS deliveries to drain (default: 60)

set -uo pipefail

NS="${NS:?set NS to the gateway namespace}"
APP_LABEL="${APP_LABEL:-app=joysafeter-agent-gateway}"
LEADER_LABEL="${LEADER_LABEL:-joysafeter-agent-gateway-leader=true}"
LEASE_NAME="${LEASE_NAME:-joysafeter-agent-gateway}"
ENVOY_LABEL="${ENVOY_LABEL:-app=joysafeter-envoy}"
SVC="${SVC:-joysafeter-agent-gateway}"
XDS_PORT="${XDS_PORT:-9092}"
HTTP_PORT="${HTTP_PORT:-9093}"
LEASE_DURATION="${LEASE_DURATION:-20}"
DURATION="${DURATION:-60}"
ITERATIONS="${ITERATIONS:-5}"
MIN_GATEWAYS="${MIN_GATEWAYS:-2}"
MIN_ENVOY_NODES="${MIN_ENVOY_NODES:-2}"
PENDING_TIMEOUT="${PENDING_TIMEOUT:-60}"

# ── output helpers ─────────────────────────────────────────────────────────
if [[ -t 1 ]]; then C_G=$'\e[32m'; C_R=$'\e[31m'; C_Y=$'\e[33m'; C_0=$'\e[0m'; else C_G=; C_R=; C_Y=; C_0=; fi
FAILS=0
log()  { printf '%s[e2e]%s %s\n' "$C_Y" "$C_0" "$*"; }
pass() { printf '%s  PASS%s %s\n' "$C_G" "$C_0" "$*"; }
fail() { printf '%s  FAIL%s %s\n' "$C_R" "$C_0" "$*"; FAILS=$((FAILS+1)); }
die()  { printf '%s[e2e] FATAL%s %s\n' "$C_R" "$C_0" "$*" >&2; exit 2; }

k() { kubectl -n "$NS" "$@"; }

# ── primitives ─────────────────────────────────────────────────────────────

# Names of pods currently carrying the leader label.
leader_pods() {
  k get pods -l "$LEADER_LABEL" -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null | sed '/^$/d'
}

leader_count() { leader_pods | grep -c . || true; }

# The single leader pod name, or empty.
leader_pod() { leader_pods | head -1; }

# Pod IP for a given pod name.
pod_ip() { k get pod "$1" -o jsonpath='{.status.podIP}' 2>/dev/null; }

# The fencing epoch. leaseTransitions is stamped as the authority epoch on every
# takeover (see bootstrap/leader.rs), so it is the observable monotonic fence.
lease_epoch() { k get lease "$LEASE_NAME" -o jsonpath='{.spec.leaseTransitions}' 2>/dev/null; }
lease_holder() { k get lease "$LEASE_NAME" -o jsonpath='{.spec.holderIdentity}' 2>/dev/null; }

# Service endpoint IPs on the xDS port (should be exactly the leader's IP).
svc_xds_endpoint_ips() {
  k get endpointslice -l "kubernetes.io/service-name=$SVC" -o json 2>/dev/null \
    | jq -r --argjson p "$XDS_PORT" '
        .items[]?
        | select(any(.ports[]?; .port == $p and (.protocol // "TCP") == "TCP"))
        | .endpoints[]?
        | select(.conditions.ready != false)
        | .addresses[]?' \
    | sort -u
}

ready_gateway_pods() {
  k get pods -l "$APP_LABEL" \
    -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.conditions[?(@.type=="Ready")].status}{"\n"}{end}' \
    2>/dev/null | awk '$2=="True"{print $1}'
}

# Wait until a predicate command succeeds or timeout (seconds) elapses.
wait_for() {
  local timeout="$1" desc="$2"; shift 2
  local deadline=$(( $(date +%s) + timeout ))
  while (( $(date +%s) < deadline )); do
    if "$@"; then return 0; fi
    sleep 1
  done
  return 1
}

gateway_count() {
  k get pods -l "$APP_LABEL" -o json | jq '[.items[] | select(.status.phase == "Running")] | length'
}

envoy_node_count() {
  k get pods -l "$ENVOY_LABEL" -o json | jq '[.items[].spec.nodeName] | unique | length'
}

leader_changed_from() {
  local previous="$1" current
  current="$(leader_pod)"
  [[ -n "$current" && "$current" != "$previous" ]]
}

endpoint_matches_current_leader() {
  local lp lip eps
  lp="$(leader_pod)"; [[ -n "$lp" ]] || return 1
  lip="$(pod_ip "$lp")"; [[ -n "$lip" ]] || return 1
  eps="$(svc_xds_endpoint_ips)"
  [[ "$(printf '%s\n' "$eps" | sed '/^$/d' | wc -l | tr -d ' ')" == "1" ]] \
    && [[ "$eps" == "$lip" ]]
}

gateway_metrics() {
  local lp
  lp="$(leader_pod)"; [[ -n "$lp" ]] || return 1
  k exec "$lp" -c agent-gateway -- \
    curl --fail --silent --max-time 3 "http://127.0.0.1:${HTTP_PORT}/metrics" 2>/dev/null
}

metric_value() {
  local name="$1"
  gateway_metrics | awk -v metric="$name" '$1 == metric { print $2; exit }'
}

pending_deliveries_drained() {
  [[ "$(metric_value joysafeter_xds_pending_deliveries)" == "0" ]]
}

all_envoy_nodes_ready() {
  local expected ready
  expected="$(envoy_node_count)"
  ready="$(metric_value joysafeter_xds_ready_envoy_nodes)"
  [[ "$expected" =~ ^[0-9]+$ && "$ready" =~ ^[0-9]+$ && "$ready" -ge "$expected" ]]
}

envoy_ready_on_node() {
  local node="$1" previous_pod="$2"
  k get pods -l "$ENVOY_LABEL" -o json | jq -e \
    --arg node "$node" --arg previous "$previous_pod" '
      any(.items[];
        .metadata.name != $previous
        and .spec.nodeName == $node
        and .status.phase == "Running"
        and any(.status.conditions[]?; .type == "Ready" and .status == "True"))' >/dev/null
}

gateway_reports_node_ready() {
  local node="$1"
  gateway_metrics | awk -v node="$node" '
    $1 == "joysafeter_xds_node_connected{node=\"" node "\"}" && $2 == 1 { connected=1 }
    $1 == "joysafeter_xds_node_ready{node=\"" node "\"}" && $2 == 1 { ready=1 }
    END { exit !(connected && ready) }'
}

# ── invariant assertions ───────────────────────────────────────────────────

assert_single_leader() {
  local n; n="$(leader_count)"
  if [[ "$n" == "1" ]]; then
    pass "exactly one leader ($(leader_pod))"
  else
    fail "expected exactly 1 leader, found $n [$(leader_pods | tr '\n' ' ')]"
  fi
}

# The leader-only Service must resolve to precisely the current leader pod IP.
assert_endpoint_follows_leader() {
  local lp lip eps
  lp="$(leader_pod)"; [[ -n "$lp" ]] || { fail "no leader pod to match endpoint against"; return; }
  lip="$(pod_ip "$lp")"
  eps="$(svc_xds_endpoint_ips | tr '\n' ' ')"
  if [[ "$(echo "$eps" | wc -w | tr -d ' ')" == "1" && "$eps" == *"$lip"* ]]; then
    pass "Service xDS endpoint == leader IP ($lip)"
  else
    fail "Service xDS endpoint [$eps] does not uniquely match leader IP ($lip)"
  fi
}

assert_lease_held() {
  local h; h="$(lease_holder)"
  if [[ -n "$h" && "$h" != "null" ]]; then
    pass "lease held by $h (epoch=$(lease_epoch))"
  else
    fail "lease has no holder"
  fi
}

# ── scenarios ──────────────────────────────────────────────────────────────

scenario_invariants() {
  log "== invariants =="
  local gateways envoy_nodes
  gateways="$(gateway_count)"
  envoy_nodes="$(envoy_node_count)"
  if (( gateways >= MIN_GATEWAYS )); then
    pass "gateway topology has $gateways running replicas"
  else
    fail "requires at least $MIN_GATEWAYS running Gateway replicas, found $gateways"
  fi
  if (( envoy_nodes >= MIN_ENVOY_NODES )); then
    pass "Envoy topology spans $envoy_nodes nodes"
  else
    fail "requires at least $MIN_ENVOY_NODES Envoy nodes, found $envoy_nodes"
  fi
  assert_single_leader
  assert_lease_held
  assert_endpoint_follows_leader
  if wait_for 60 "all Envoy nodes xDS-ready" all_envoy_nodes_ready; then
    pass "all Envoy nodes are connected and xDS-ready"
  else
    fail "not all Envoy nodes became xDS-ready within 60s"
  fi
  if wait_for "$PENDING_TIMEOUT" "pending xDS deliveries drain" pending_deliveries_drained; then
    pass "pending xDS deliveries drained"
  else
    fail "xDS pending deliveries did not drain within ${PENDING_TIMEOUT}s"
  fi
}

scenario_failover() {
  log "== failover: kill the leader, expect clean takeover =="
  local old_leader old_epoch old_ip new_leader new_epoch
  old_leader="$(leader_pod)";  [[ -n "$old_leader" ]] || die "no current leader"
  old_epoch="$(lease_epoch)"
  old_ip="$(pod_ip "$old_leader")"
  log "current leader=$old_leader ip=$old_ip epoch=$old_epoch; deleting it"
  k delete pod "$old_leader" --wait=false >/dev/null

  # A new, different leader must appear within lease_duration + renew slack.
  if wait_for $((LEASE_DURATION + 15)) "new leader" leader_changed_from "$old_leader"; then
    new_leader="$(leader_pod)"
    pass "new leader elected: $new_leader (was $old_leader)"
  else
    fail "no new leader within $((LEASE_DURATION+15))s"; return
  fi

  assert_single_leader

  # Fencing epoch must strictly advance so a superseded leader can never validate.
  new_epoch="$(lease_epoch)"
  if [[ -n "$new_epoch" && -n "$old_epoch" && "$new_epoch" -gt "$old_epoch" ]]; then
    pass "fencing epoch advanced: $old_epoch -> $new_epoch"
  else
    fail "fencing epoch did not advance: $old_epoch -> $new_epoch"
  fi

  # Service must re-point to the new leader (so Envoy/orchestrator reach it).
  if wait_for 30 "endpoint re-point" endpoint_matches_current_leader; then
    pass "Service endpoint moved to new leader"
  else
    fail "Service endpoint did not converge to new leader within 30s"
  fi

  if wait_for "$PENDING_TIMEOUT" "pending xDS deliveries drain" pending_deliveries_drained; then
    pass "pending xDS deliveries drained after failover"
  else
    fail "xDS pending deliveries remained after failover"
  fi
}

scenario_split_brain_watch() {
  log "== split-brain watch: poll leader count for ${DURATION}s =="
  local deadline max=0 n
  deadline=$(( $(date +%s) + DURATION ))
  while (( $(date +%s) < deadline )); do
    n="$(leader_count)"
    (( n > max )) && max="$n"
    if (( n > 1 )); then
      fail "SPLIT BRAIN: $n leaders at once [$(leader_pods | tr '\n' ' ')]"
      return
    fi
    sleep 1
  done
  pass "never observed >1 leader over ${DURATION}s (max=$max)"
}

scenario_envoy_recovery() {
  log "== envoy recovery: kill an Envoy, expect ADS reconnect =="
  local envoy node
  envoy="$(k get pods -l "$ENVOY_LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
  [[ -n "$envoy" ]] || { log "no Envoy pods labelled $ENVOY_LABEL; skipping"; return; }
  node="$(k get pod "$envoy" -o jsonpath='{.spec.nodeName}')"
  log "deleting Envoy pod $envoy on node $node"
  k delete pod "$envoy" --wait=false >/dev/null
  if wait_for 120 "replacement Envoy ready" envoy_ready_on_node "$node" "$envoy"; then
    pass "replacement Envoy became Ready on $node"
  else
    fail "replacement Envoy did not become Ready on $node within 120s"
    return
  fi

  if wait_for 90 "ADS reconnect" gateway_reports_node_ready "$node"; then
    pass "Gateway reports Envoy node $node connected and xDS-ready"
  else
    fail "Gateway did not report Envoy node $node ready within 90s"
  fi

  if wait_for "$PENDING_TIMEOUT" "pending xDS deliveries drain" pending_deliveries_drained; then
    pass "pending xDS deliveries drained after Envoy reconnect"
  else
    fail "xDS pending deliveries remained after Envoy reconnect"
  fi
}

scenario_soak() {
  log "== soak: $ITERATIONS failover rounds =="
  local i
  for ((i=1;i<=ITERATIONS;i++)); do
    log "--- round $i/$ITERATIONS ---"
    scenario_failover
    scenario_invariants
    sleep 5
  done
}

# ── main ───────────────────────────────────────────────────────────────────
command -v jq >/dev/null || die "jq is required"
command -v kubectl >/dev/null || die "kubectl is required"
k get ns "$NS" >/dev/null 2>&1 || die "namespace $NS not found"

case "${1:-invariants}" in
  invariants)         scenario_invariants ;;
  failover)           scenario_failover; scenario_invariants ;;
  split-brain-watch)  scenario_split_brain_watch ;;
  envoy-recovery)     scenario_envoy_recovery ;;
  soak)               scenario_soak ;;
  all)
    scenario_invariants
    scenario_failover
    scenario_invariants
    scenario_envoy_recovery
    DURATION=30 scenario_split_brain_watch
    ;;
  *) die "unknown subcommand: ${1:-}. See header for usage." ;;
esac

echo
if (( FAILS == 0 )); then
  printf '%s[e2e] ALL CHECKS PASSED%s\n' "$C_G" "$C_0"; exit 0
else
  printf '%s[e2e] %d CHECK(S) FAILED%s\n' "$C_R" "$FAILS" "$C_0"; exit 1
fi
