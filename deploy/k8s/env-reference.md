# =============================================================================
# JoySafeter K8s Deployment — Configuration Reference
# =============================================================================
#
# 本文件是 K8s 部署的配置参考(非直接使用的 .env 文件)。
# K8s 部署配置分三层:
#
#   1. Secret (敏感): kubectl create secret generic joysafeter-secrets ...
#   2. YAML env (非敏感): orchestrator-complete.yaml 里的 env 字段
#   3. 默认值 (不用设): 代码里有合理默认
#
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# 第一层: Secret (必须手动创建)
# kubectl create secret generic joysafeter-secrets -n joysafeter \
#   --from-literal=DATABASE_URL="..." \
#   --from-literal=REDIS_URL="..." \
#   --from-literal=SECRET_KEY="..." \
#   --from-literal=JOYSAFETER_VAULT_ENCRYPTION_KEY="..."
# ─────────────────────────────────────────────────────────────────────────────

# 云 PostgreSQL 连接串 (asyncpg driver)
DATABASE_URL=postgresql+asyncpg://user:password@pg-host:5432/joysafeter

# 云 Redis 连接串
REDIS_URL=redis://:password@redis-host:6379/0

# 应用密钥 (openssl rand -hex 32)
SECRET_KEY=CHANGE_ME

# Vault 加密密钥 (openssl rand -base64 32)
JOYSAFETER_VAULT_ENCRYPTION_KEY=CHANGE_ME


# ─────────────────────────────────────────────────────────────────────────────
# 第二层: YAML env (在 orchestrator-complete.yaml 里设)
# 以下是完整列表和推荐值
# ─────────────────────────────────────────────────────────────────────────────

# ── 基础 ──
RUST_LOG=info
# JOYSAFETER_INSTANCE_ID 和 POD_NAME 自动从 K8s fieldRef 注入,不用设

# ── gRPC ──
JOYSAFETER_GRPC_HOST=0.0.0.0
JOYSAFETER_GRPC_PORT=9090
JOYSAFETER_GRPC_PUBLIC_URL=http://joysafeter-orchestrator:9090
JOYSAFETER_GRPC_MAX_CONNECTIONS=5000

# ── Sandbox Provider ──
JOYSAFETER_SANDBOX_PROVIDER=k8s
JOYSAFETER_K8S_NAMESPACE=joysafeter
JOYSAFETER_SANDBOX_IMAGE=your-registry/joysafeter-claudecode:latest
JOYSAFETER_IMAGE_CLAUDE=your-registry/joysafeter-claudecode:latest
JOYSAFETER_IMAGE_CODEX=your-registry/joysafeter-codex:latest
JOYSAFETER_IMAGE_NATIVE=your-registry/joysafeter-native:latest

# ── Leader Election (HA) ──
JOYSAFETER_LEADER_ELECTION_ENABLED=true
JOYSAFETER_LEADER_LEASE_NAME=joysafeter-orchestrator-leader
JOYSAFETER_LEADER_LEASE_DURATION_SEC=10
JOYSAFETER_LEADER_RENEW_INTERVAL_SEC=3

# ── Envoy Egress ──
JOYSAFETER_ENVOY_ENABLED=true
JOYSAFETER_ENVOY_XDS_MODE=grpc
JOYSAFETER_ENVOY_SOCKET_HOST_DIR=/data/joysafeter/envoy-sockets
JOYSAFETER_ENVOY_CONTAINER_NAME=joysafeter-envoy
JOYSAFETER_ENVOY_GRPC_HOST=joysafeter-orchestrator
JOYSAFETER_ENVOY_GRPC_PORT=9090
JOYSAFETER_ENVOY_NETWORK=joysafeter

# LLM 凭证注入允许的上游 host (逗号分隔)
JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS=ai-api.jdcloud.com,api.anthropic.com,api.openai.com,generativelanguage.googleapis.com

# ── Runtime ──
JOYSAFETER_MAX_CONCURRENT_TASKS=500
JOYSAFETER_TASK_DEFAULT_TIMEOUT=7200
JOYSAFETER_SANDBOX_IDLE_TIMEOUT=300
JOYSAFETER_EVENT_STREAM_ENABLED=true
JOYSAFETER_EVENT_STREAM_KEY=joysafeter:orchestrator:events
JOYSAFETER_EVENT_STREAM_GROUP=joysafeter-orchestrator-event-workers
JOYSAFETER_REDIS_QUEUE_PREFIX=joysafeter
DISABLE_TELEMETRY=1


# ─────────────────────────────────────────────────────────────────────────────
# 第三层: 使用默认值 (不需要设,仅供参考)
# ─────────────────────────────────────────────────────────────────────────────

# Sandbox 生命周期
# JOYSAFETER_SANDBOX_STOPPED_TTL=3600        # 停止后保留 1h
# JOYSAFETER_SANDBOX_HARD_TIMEOUT=14400      # 最大运行 4h
# JOYSAFETER_SANDBOX_FAILURE_THRESHOLD=3     # 连续失败 3 次标记故障

# Task 调度
# JOYSAFETER_MAX_SCHEDULING_TASKS=300
# JOYSAFETER_SCHEDULER_BATCH_SIZE=10
# JOYSAFETER_TASK_DEFAULT_MAX_RETRIES=2

# Event stream 调优
# JOYSAFETER_EVENT_STREAM_MAX_LEN=100000
# JOYSAFETER_EVENT_STREAM_BATCH_SIZE=100
# JOYSAFETER_EVENT_STREAM_BLOCK_MS=1000

# Heartbeat (Redis 实例注册)
# JOYSAFETER_HEARTBEAT_INTERVAL=15
# JOYSAFETER_HEARTBEAT_TTL=45

# Sandbox pool (K8s + Envoy 模式下自动禁用)
# JOYSAFETER_SANDBOX_POOL_ENABLED=false

# Envoy 高级配置 (通常不用改)
# JOYSAFETER_ENVOY_SOCKET_READY_TIMEOUT_MS=30000
# JOYSAFETER_ENVOY_WRITE_DEBUG_ENTRIES=false
# JOYSAFETER_ENVOY_IMAGE=envoyproxy/envoy:v1.37.1

# K8s 高级（控制器使用 kube-rs，不依赖 kubectl）
# JOYSAFETER_K8S_KUBECTL_PATH=kubectl
# JOYSAFETER_K8S_ORCHESTRATOR_URL=http://joysafeter-orchestrator:9090


# ─────────────────────────────────────────────────────────────────────────────
# 不适用于 K8s 部署 (单机 Docker Compose 专用)
# ─────────────────────────────────────────────────────────────────────────────
# JOYSAFETER_RUNNER_CONTROL_SOCKET_HOST_DIR  → K8s 用 TCP Service
# JOYSAFETER_RUNNER_CONTROL_SOCKET_VOLUME    → K8s 不需要
# JOYSAFETER_RUNNER_CONTROL_SOCKET_CONTAINER_PATH → K8s 不需要
# JOYSAFETER_ENVOY_CONFIG_DIR               → DaemonSet 内嵌 bootstrap
# JOYSAFETER_ENVOY_SOCKET_VOLUME            → K8s 用 hostPath
# JOYSAFETER_ENVOY_SOCKET_SUBPATH_MOUNT     → K8s 用 subPath
# JOYSAFETER_SANDBOX_WORKSPACE_ROOT         → K8s 用 emptyDir/PVC
# DOCKER_SOCKET_PATH                        → K8s 用 kube-rs API
