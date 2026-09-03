# =============================================================================
# JoySafeter K8s Deployment — Configuration Reference
# =============================================================================
#
# 本文件是 K8s 部署的配置参考(非直接使用的 .env 文件)。
# Helm/Kubernetes 部署配置分三层:
#
#   1. Secret (敏感): deploy/deploy.sh k8s secrets ...
#   2. Helm values (非敏感): deploy/helm/joysafeter-orchestrator/values*.yaml
#   3. 默认值 (不用设): 代码里有合理默认
#
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# 第一层: Secret
# 统一入口:
#   DATABASE_URL=... REDIS_URL=... JOYSAFETER_VAULT_ENCRYPTION_KEY=... \
#     ./deploy/deploy.sh k8s secrets --namespace joysafeter --from-env
# 其他可选 Secret key 由 Helm chart 的 externalSecret 契约管理。
# ─────────────────────────────────────────────────────────────────────────────

# 云 PostgreSQL 连接串 (asyncpg driver)
DATABASE_URL=postgresql+asyncpg://user:password@pg-host:5432/joysafeter

# 云 Redis 连接串
REDIS_URL=redis://:password@redis-host:6379/0

# 旧版 Vault 加密密钥，仅用于 enc:/enc:v1: 历史密文兼容
JOYSAFETER_VAULT_ENCRYPTION_KEY=
JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING=
JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID=
JOYSAFETER_XDS_AUTH_KEYRING=
JOYSAFETER_XDS_AUTH_WRITE_KEY_ID=
JOYSAFETER_XDS_AUTH_TOKEN=
JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN=
JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN=


# ─────────────────────────────────────────────────────────────────────────────
# 第二层: Helm values (在 values.yaml 或环境 values 文件里设)
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

# 独立 Agent Gateway（Helm 固定部署）
JOYSAFETER_AGENT_GATEWAY_URL=http://joysafeter-agent-gateway:9093
JOYSAFETER_AGENT_GATEWAY_XDS_PORT=9092
JOYSAFETER_AGENT_GATEWAY_HTTP_PORT=9093
JOYSAFETER_AGENT_GATEWAY_REQUEST_TIMEOUT_SECS=25
JOYSAFETER_AGENT_GATEWAY_NODE_VISIBILITY=node_scoped
JOYSAFETER_AGENT_GATEWAY_LEADER_ELECTION_ENABLED=true
JOYSAFETER_AGENT_GATEWAY_LEADER_LEASE_NAME=joysafeter-agent-gateway
JOYSAFETER_AGENT_GATEWAY_LEADER_LEASE_DURATION_SECS=15
JOYSAFETER_AGENT_GATEWAY_LEADER_RENEW_INTERVAL_SECS=5
JOYSAFETER_AGENT_GATEWAY_REPLICATION_URL=http://joysafeter-agent-gateway:9093
JOYSAFETER_AGENT_GATEWAY_HOT_STANDBY_MIN_ACKS=1
JOYSAFETER_AGENT_GATEWAY_REPLICATION_ACK_TIMEOUT_MS=1000
JOYSAFETER_AGENT_GATEWAY_DELIVERY_TIMEOUT_SECS=30
JOYSAFETER_AGENT_GATEWAY_SHUTDOWN_GRACE_SECS=10

# ── Sandbox Provider ──
JOYSAFETER_SANDBOX_PROVIDER=k8s
JOYSAFETER_K8S_NAMESPACE=joysafeter
JOYSAFETER_K8S_PRIORITY_CLASS_NAME=
JOYSAFETER_K8S_NODE_SELECTOR={}
JOYSAFETER_K8S_TOLERATIONS=[]
JOYSAFETER_SANDBOX_IMAGE=your-registry/joysafeter-claudecode:latest
JOYSAFETER_IMAGE_CLAUDE=your-registry/joysafeter-claudecode:latest
JOYSAFETER_IMAGE_CODEX=your-registry/joysafeter-codex:latest
JOYSAFETER_IMAGE_NATIVE=your-registry/joysafeter-native:latest
JOYSAFETER_IMAGE_PI=your-registry/joysafeter-pi:latest

# ── Envoy Egress ──
JOYSAFETER_ENVOY_ENABLED=true
JOYSAFETER_ENVOY_XDS_MODE=grpc
JOYSAFETER_ENVOY_SOCKET_HOST_DIR=/data/joysafeter/envoy-sockets
JOYSAFETER_ENVOY_GRPC_HOST=joysafeter-agent-gateway

# LLM 凭证注入允许的上游 host (逗号分隔)
JOYSAFETER_LLM_EGRESS_ALLOWED_HOSTS=ai-api.jdcloud.com,api.anthropic.com,api.openai.com,generativelanguage.googleapis.com

# ── Runtime ──
JOYSAFETER_MAX_CONCURRENT_TASKS=500
JOYSAFETER_TASK_DEFAULT_TIMEOUT=7200
JOYSAFETER_SANDBOX_IDLE_TIMEOUT=300
JOYSAFETER_EVENT_STREAM_ENABLED=true
JOYSAFETER_EVENT_STREAM_KEY=joysafeter:orchestrator:events
JOYSAFETER_REDIS_QUEUE_PREFIX=joysafeter


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

# Event stream 发布端调优
# JOYSAFETER_EVENT_STREAM_MAX_LEN=100000

# Heartbeat (Redis 实例注册)
# JOYSAFETER_HEARTBEAT_INTERVAL=15
# JOYSAFETER_HEARTBEAT_TTL=45

# Sandbox pool
# JOYSAFETER_SANDBOX_POOL_ENABLED=false

# Envoy 高级配置
# JOYSAFETER_ENVOY_SOCKET_READY_TIMEOUT_MS=30000

# K8s 高级
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
