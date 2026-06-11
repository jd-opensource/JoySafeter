#!/bin/bash
#
# Environment Networking E2E Test
#
# Tests:
#   Phase 1: Package installation via Docker image build
#   Phase 2: Envoy forward-proxy setup
#   Phase 3: Network policy enforcement (allow/block)
#   Phase 4: Combined verification (packages + networking)
#
# Prerequisites:
#   - Docker daemon running
#   - joysafeter-net Docker network exists
#   - joysafeter-claudecode:latest image available
#   - Envoy image available
#
# Usage:
#   bash scripts/e2e_environment_networking.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/e2e_helpers.sh"

SOCKET_VOLUME="joysafeter-e2e-net-sockets"
CONFIG_DIR="/tmp/joysafeter-e2e-net-config"
SANDBOX_ID="e2e-net-sandbox"
ENVOY_CONTAINER="joysafeter-e2e-net-envoy"
TEST_CONTAINER="joysafeter-e2e-net-test"
ENV_IMAGE="joysafeter/e2e-net-test:v1"
NETWORK="joysafeter-net"
ENVOY_IMAGE="swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/envoyproxy/envoy:v1.35.3-linuxarm64"
BASE_IMAGE="joysafeter-claudecode:latest"

cleanup() {
    echo ""
    echo "=== Cleanup ==="
    docker rm -f "$TEST_CONTAINER" 2>/dev/null || true
    docker rm -f "$ENVOY_CONTAINER" 2>/dev/null || true
    docker volume rm "$SOCKET_VOLUME" 2>/dev/null || true
    docker rmi "$ENV_IMAGE" 2>/dev/null || true
    rm -rf "$CONFIG_DIR" 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT

echo "╔══════════════════════════════════════════════════════════╗"
echo "║  Environment Networking E2E Test                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  Base image: $BASE_IMAGE"
echo "  Packages: apt(jq)"
echo "  Networking: restricted, allowed_hosts=[httpbin.org]"
echo ""

# ══════════════════════════════════════════════════════════
# PHASE 1: Package Installation
# ══════════════════════════════════════════════════════════
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PHASE 1: Package Installation                          ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

echo ">>> Step 1: Build environment image with packages"

DOCKERFILE=$(cat << 'EOF'
FROM joysafeter-claudecode:latest
USER root
RUN apt-get update && apt-get install -y --no-install-recommends jq && rm -rf /var/lib/apt/lists/*
USER agent
EOF
)
echo "$DOCKERFILE"
echo ""

echo "$DOCKERFILE" | docker build -t "$ENV_IMAGE" -f - . 2>&1 | tail -5

if docker image inspect "$ENV_IMAGE" > /dev/null 2>&1; then
    pass "Environment image built: $ENV_IMAGE"
else
    fail "Failed to build environment image"
    exit 1
fi

# Step 2: Verify packages in image
echo ""
echo ">>> Step 2: Verify packages installed"

JQ_VERSION=$(docker run --rm --entrypoint sh "$ENV_IMAGE" -c "jq --version" 2>&1 || echo "NOT FOUND")
if echo "$JQ_VERSION" | grep -q "jq-"; then
    pass "apt package 'jq': $JQ_VERSION"
else
    fail "apt package 'jq' not found: $JQ_VERSION"
fi

# Step 3: Verify base image doesn't have these packages
echo ""
echo ">>> Step 3: Confirm base image lacks packages"

BASE_JQ=$(docker run --rm --entrypoint sh "$BASE_IMAGE" -c "which jq 2>/dev/null || echo MISSING")
if [ "$BASE_JQ" = "MISSING" ]; then
    pass "Base image does NOT have 'jq'"
else
    fail "Base image already has 'jq'"
fi

# ══════════════════════════════════════════════════════════
# PHASE 2: Envoy Proxy Setup
# ══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PHASE 2: Envoy Proxy Setup                             ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

echo ">>> Step 4: Generate Envoy configuration"

rm -rf "$CONFIG_DIR"
mkdir -p "$CONFIG_DIR"

docker volume rm "$SOCKET_VOLUME" 2>/dev/null || true
docker volume create "$SOCKET_VOLUME" > /dev/null

docker run --rm \
    -v "$SOCKET_VOLUME:/sockets" \
    --entrypoint sh \
    "$ENVOY_IMAGE" -c "mkdir -p /sockets/$SANDBOX_ID && chmod 777 /sockets /sockets/$SANDBOX_ID"

cat > "$CONFIG_DIR/bootstrap.yaml" << 'EOF'
node:
  cluster: joysafeter-proxy
  id: joysafeter-e2e-envoy

dynamic_resources:
  lds_config:
    path_config_source:
      path: /envoy-config/lds.yaml
      watched_directory:
        path: /envoy-config

static_resources:
  clusters:
    - name: dynamic_forward_proxy
      connect_timeout: 10s
      lb_policy: CLUSTER_PROVIDED
      cluster_type:
        name: envoy.clusters.dynamic_forward_proxy
        typed_config:
          "@type": type.googleapis.com/envoy.extensions.clusters.dynamic_forward_proxy.v3.ClusterConfig
          dns_cache_config:
            name: dynamic_forward_proxy_cache
            dns_lookup_family: V4_ONLY

admin:
  address:
    socket_address:
      address: 127.0.0.1
      port_value: 9901
EOF

cat > "$CONFIG_DIR/lds.yaml" << EOF
version_info: "1"
resources:
  - "@type": type.googleapis.com/envoy.config.listener.v3.Listener
    name: e2e_http_proxy
    address:
      pipe:
        path: /sockets/$SANDBOX_ID/http.sock
        mode: 438
    filter_chains:
      - filters:
          - name: envoy.filters.network.http_connection_manager
            typed_config:
              "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
              stat_prefix: e2e_http
              http_protocol_options:
                allow_absolute_url: true
              upgrade_configs:
                - upgrade_type: CONNECT
              route_config:
                virtual_hosts:
                  - name: allowed_hosts
                    domains:
                      - "httpbin.org"
                      - "httpbin.org:443"
                      - "httpbin.org:80"
                      - "pypi.org"
                      - "pypi.org:443"
                    routes:
                      - match:
                          connect_matcher: {}
                        route:
                          cluster: dynamic_forward_proxy
                          upgrade_configs:
                            - upgrade_type: CONNECT
                      - match:
                          prefix: "/"
                        route:
                          cluster: dynamic_forward_proxy
                  - name: deny_all
                    domains: ["*"]
                    routes:
                      - match:
                          prefix: "/"
                        direct_response:
                          status: 403
                          body:
                            inline_string: "BLOCKED: host not in allowlist"
              http_filters:
                - name: envoy.filters.http.dynamic_forward_proxy
                  typed_config:
                    "@type": type.googleapis.com/envoy.extensions.filters.http.dynamic_forward_proxy.v3.FilterConfig
                    dns_cache_config:
                      name: dynamic_forward_proxy_cache
                      dns_lookup_family: V4_ONLY
                - name: envoy.filters.http.router
                  typed_config:
                    "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
EOF

pass "Envoy config generated (allowlist: httpbin.org, pypi.org)"

# Step 5: Start Envoy container
echo ""
echo ">>> Step 5: Start Envoy container"

docker rm -f "$ENVOY_CONTAINER" 2>/dev/null || true
docker run -d \
    --name "$ENVOY_CONTAINER" \
    --network "$NETWORK" \
    -v "$SOCKET_VOLUME:/sockets" \
    -v "$CONFIG_DIR:/envoy-config:ro" \
    "$ENVOY_IMAGE" \
    envoy -c /envoy-config/bootstrap.yaml --drain-time-s 1 -l info > /dev/null

echo -n "Waiting for Envoy socket"
for i in $(seq 1 30); do
    if docker exec "$ENVOY_CONTAINER" test -S "/sockets/$SANDBOX_ID/http.sock" 2>/dev/null; then
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo ""
        fail "Envoy socket not created within 30s"
        docker logs "$ENVOY_CONTAINER" 2>&1 | tail -10
        exit 1
    fi
    sleep 1
    echo -n "."
done
echo ""
pass "Envoy container running, socket created"

# Step 6: Start test container
echo ""
echo ">>> Step 6: Start test container (--network none)"

docker rm -f "$TEST_CONTAINER" 2>/dev/null || true
docker run -d \
    --name "$TEST_CONTAINER" \
    --network none \
    --entrypoint sleep \
    -v "$SOCKET_VOLUME:/sockets" \
    "$ENV_IMAGE" \
    3600 > /dev/null

pass "Test container started: image=$ENV_IMAGE, network=none"

# ══════════════════════════════════════════════════════════
# PHASE 3: Network Policy Verification
# ══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PHASE 3: Network Policy Verification                   ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

# Step 7: Verify network isolation
echo ">>> Step 7: Verify network isolation"

HAS_ETH=$(docker exec "$TEST_CONTAINER" sh -c "cat /proc/net/dev | grep eth0 || echo NONE")
if [ "$HAS_ETH" = "NONE" ]; then
    pass "No eth0 interface (--network none confirmed)"
else
    fail "Container has eth0 — network isolation broken!"
fi

if docker exec "$TEST_CONTAINER" test -S "/sockets/$SANDBOX_ID/http.sock"; then
    pass "Proxy socket accessible inside container"
else
    fail "Proxy socket NOT accessible"
fi

# Step 8: Direct internet impossible
echo ""
echo ">>> Step 8: Direct internet access impossible"

DIRECT=$(docker exec "$TEST_CONTAINER" sh -c \
    "curl -s -o /dev/null -w '%{http_code}' http://httpbin.org/get --connect-timeout 5 --max-time 8 2>/dev/null || true")
if [ "$DIRECT" = "000" ]; then
    pass "Direct access → connection failed (no network)"
else
    fail "Direct access → $DIRECT (expected 000)"
fi

# Step 9: Allowed host via proxy
echo ""
echo ">>> Step 9: ALLOWED host — httpbin.org"

HTTP_RESULT=$(docker exec "$TEST_CONTAINER" \
    curl -s -o /dev/null -w '%{http_code}' \
    --unix-socket "/sockets/$SANDBOX_ID/http.sock" \
    http://httpbin.org/get \
    --connect-timeout 15 --max-time 30 2>&1 || echo "000")

if [ "$HTTP_RESULT" = "200" ]; then
    pass "HTTP GET httpbin.org/get → 200 OK"
else
    fail "HTTP GET httpbin.org/get → $HTTP_RESULT (expected 200)"
fi

# Step 10: Blocked hosts via proxy
echo ""
echo ">>> Step 10: BLOCKED hosts"

for HOST in google.com example.com github.com; do
    BLOCKED_CODE=$(docker exec "$TEST_CONTAINER" \
        curl -s -o /dev/null -w '%{http_code}' \
        --unix-socket "/sockets/$SANDBOX_ID/http.sock" \
        "http://$HOST/" \
        --connect-timeout 15 --max-time 30 2>&1 || echo "000")

    if [ "$BLOCKED_CODE" = "403" ]; then
        pass "HTTP GET $HOST → 403 (blocked)"
    else
        fail "HTTP GET $HOST → $BLOCKED_CODE (expected 403)"
    fi
done

# Step 11: Response body validation
echo ""
echo ">>> Step 11: Response body validation"

ALLOWED_BODY=$(docker exec "$TEST_CONTAINER" \
    curl -s --unix-socket "/sockets/$SANDBOX_ID/http.sock" \
    http://httpbin.org/get --connect-timeout 15 --max-time 30 2>&1 || echo "ERROR")

if echo "$ALLOWED_BODY" | grep -q '"origin"'; then
    pass "Allowed response contains 'origin' field"
else
    fail "Allowed response invalid: $(echo "$ALLOWED_BODY" | head -3)"
fi

BLOCK_BODY=$(docker exec "$TEST_CONTAINER" \
    curl -s --unix-socket "/sockets/$SANDBOX_ID/http.sock" \
    http://google.com/ --connect-timeout 15 --max-time 30 2>&1 || echo "")

if echo "$BLOCK_BODY" | grep -q "not in allowlist"; then
    pass "Blocked response: 'BLOCKED: host not in allowlist'"
else
    fail "Unexpected block body: $BLOCK_BODY"
fi

# ══════════════════════════════════════════════════════════
# PHASE 4: Combined Verification
# ══════════════════════════════════════════════════════════
echo ""
echo "┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
echo "┃  PHASE 4: Combined Verification                         ┃"
echo "┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛"
echo ""

echo ">>> Step 12: Verify packages work inside sandbox"

SANDBOX_JQ=$(docker exec "$TEST_CONTAINER" sh -c 'echo "{\"test\":123}" | jq .test' 2>&1 || echo "ERROR")
if [ "$SANDBOX_JQ" = "123" ]; then
    pass "jq works inside sandbox"
else
    fail "jq failed in sandbox: $SANDBOX_JQ"
fi

echo ""
echo ">>> Step 13: Combined — use jq to parse proxy response"

ORIGIN=$(docker exec "$TEST_CONTAINER" sh -c "
    curl -s --unix-socket /sockets/$SANDBOX_ID/http.sock http://httpbin.org/get --max-time 30 | jq -r .origin
" 2>&1 || echo "ERROR")

if echo "$ORIGIN" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$'; then
    pass "jq + proxy: origin=$ORIGIN (packages + networking work together)"
else
    fail "Combined test failed: origin=$ORIGIN"
fi

# ══════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════
print_summary

if [ $? -eq 0 ]; then
    echo "Environment networking verified:"
    echo "  - Packages: apt (jq) installed and working"
    echo "  - Networking: --network none isolation confirmed"
    echo "  - Networking: allowed host (httpbin.org) accessible via proxy"
    echo "  - Networking: blocked hosts (google, github, example) get 403"
    echo "  - Combined: installed package processes proxied responses"
fi

exit $FAILED
