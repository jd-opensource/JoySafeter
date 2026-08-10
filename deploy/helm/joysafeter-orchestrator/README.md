# JoySafeter Orchestrator Helm Chart

## 部署

### 前置: 手工创建两个 Secret (每个环境只需一次, 一般不变)

所有敏感信息（仓库账号、DB/Redis 密码、Vault 密钥）**不写进 values 文件**，
统一手工创建为 K8s Secret，chart 只按名称引用。

**1. 私有仓库拉取凭证** (`aisec-repo-cred`)

```bash
# 预发
kubectl create namespace joysafeter-pre
kubectl create secret docker-registry aisec-repo-cred -n joysafeter-pre \
  --docker-server=aisec-repo.jd.com \
  --docker-username=<user> --docker-password=<pass>

# 生产
kubectl create namespace joysafeter-prod
kubectl create secret docker-registry aisec-repo-cred -n joysafeter-prod \
  --docker-server=aisec-repo.jd.com \
  --docker-username=<user> --docker-password=<pass>
```

**2. DB / Redis / Vault 凭证** (`joysafeter-secrets-{env}`)

Orchestrator 从 `POSTGRES_*` / `REDIS_*` 拆分字段组装连接串（密码内部自动
URL-encode，无需手动处理 `@#!`），Vault 密钥用 `JOYSAFETER_VAULT_ENCRYPTION_KEY`。

```bash
# 预发
kubectl create secret generic joysafeter-secrets-pre -n joysafeter-pre \
  --from-literal=POSTGRES_HOST=pgm-xxx-pre.pg.rds.jdcloud.com \
  --from-literal=POSTGRES_PORT=5432 \
  --from-literal=POSTGRES_USER=joysafeter \
  --from-literal=POSTGRES_PASSWORD='<密码>' \
  --from-literal=POSTGRES_DB=joysafeter_pre \
  --from-literal=REDIS_HOST=redis-xxx-pre.redis.rds.jdcloud.com \
  --from-literal=REDIS_PORT=6379 \
  --from-literal=REDIS_PASSWORD='<密码>' \
  --from-literal=REDIS_DB=0 \
  --from-literal=JOYSAFETER_VAULT_ENCRYPTION_KEY="$(openssl rand -base64 32)"

# 生产 (namespace / host / db 名替换为 prod)
kubectl create secret generic joysafeter-secrets-prod -n joysafeter-prod \
  --from-literal=POSTGRES_HOST=pgm-xxx-prod.pg.rds.jdcloud.com \
  --from-literal=POSTGRES_PORT=5432 \
  --from-literal=POSTGRES_USER=joysafeter \
  --from-literal=POSTGRES_PASSWORD='<密码>' \
  --from-literal=POSTGRES_DB=joysafeter_prod \
  --from-literal=REDIS_HOST=redis-xxx-prod.redis.rds.jdcloud.com \
  --from-literal=REDIS_PORT=6379 \
  --from-literal=REDIS_PASSWORD='<密码>' \
  --from-literal=REDIS_DB=0 \
  --from-literal=JOYSAFETER_VAULT_ENCRYPTION_KEY="$(openssl rand -base64 32)"
```

> 云 Redis/PG 走 TLS 时，追加 `--from-literal=REDIS_SCHEME=rediss` /
> `--from-literal=POSTGRES_SSLMODE=require`。

**3. 给 default SA 附加拉取凭证** (sandbox Pod 用 default SA 创建, 需继承此凭证拉私有镜像)

```bash
kubectl patch serviceaccount default -n joysafeter-pre \
  -p '{"imagePullSecrets":[{"name":"aisec-repo-cred"}]}'
# 生产同理, -n joysafeter-prod
```

> default SA 是 K8s 每个 namespace 自建、非 Helm 管理, 故手工 patch 一次即可 (幂等)。

values 文件里只保留两处**引用名**（非敏感）：
- `externalSecret: joysafeter-secrets-{env}` — DB/Redis/Vault Secret
- `image.imagePullSecrets: [aisec-repo-cred]` — 仓库拉取凭证

### 1. Helm 部署

```bash
cd deploy/helm/joysafeter-orchestrator

# 预发
helm install joysafeter-pre . -f values-pre.yaml -n joysafeter-pre

# 生产
helm install joysafeter-prod . -f values-prod.yaml -n joysafeter-prod
```

### 2. 升级

```bash
helm upgrade joysafeter-pre . -f values-pre.yaml
helm upgrade joysafeter-prod . -f values-prod.yaml
```

### 3. 扩缩容

```bash
kubectl scale deployment joysafeter-orchestrator -n joysafeter-prod --replicas=5
```

## 配置说明

### 敏感凭证 (手工创建的 Secret, 不在 values 里)

| Secret | Key | 说明 |
|--------|-----|------|
| `joysafeter-secrets-{env}` | `POSTGRES_HOST/PORT/USER/PASSWORD/DB` | 云 PG 连接 (密码内部自动 URL-encode) |
| `joysafeter-secrets-{env}` | `REDIS_HOST/PORT/PASSWORD/DB` | 云 Redis 连接 |
| `joysafeter-secrets-{env}` | `REDIS_SCHEME` | 可选, TLS 时 `rediss` |
| `joysafeter-secrets-{env}` | `POSTGRES_SSLMODE` | 可选, 强制 SSL 时 `require` |
| `joysafeter-secrets-{env}` | `JOYSAFETER_VAULT_ENCRYPTION_KEY` | Vault 加密密钥 |
| `aisec-repo-cred` | `.dockerconfigjson` | 私有仓库拉取凭证 |

> Deployment 通过 `envFrom.secretRef` 注入 `joysafeter-secrets-{env}` 的全部 key，
> 通过 `imagePullSecrets` 引用 `aisec-repo-cred`。

### 非敏感配置 (values.yaml)

通过 `values-pre.yaml` / `values-prod.yaml` 覆盖：

| 参数 | 默认 | 说明 |
|------|------|------|
| `haMode` | `multi` | HA 模式: standalone/leader/multi |
| `orchestrator.replicas` | 3 | Orchestrator 副本数 |
| `orchestrator.pool.minSize` | 5 | 预热池最小沙箱数 |
| `orchestrator.sandbox.idleTimeout` | 300 | 沙箱空闲超时(秒) |
| `envoy.socketHostDir` | `/data/joysafeter/envoy-sockets` | Envoy UDS hostPath |
| `egress.allowedHosts` | [见 values.yaml] | Envoy 出站白名单 |

### 预发 vs 生产差异

| 参数 | 预发 (pre) | 生产 (prod) |
|------|------|------|
| namespace | `joysafeter-pre` | `joysafeter-prod` |
| replicas | 1 | 3 |
| pool.minSize | 2 | 10 |
| sandbox.idleTimeout | 120s | 300s |
| sandbox.hardTimeout | 1h | 6h |
| logLevel | debug | info |
| envoy.socketHostDir | `/data/joysafeter-pre/...` | `/data/joysafeter-prod/...` |
| DB/Redis | pre 云实例 | prod 云实例 |

## 架构

```
Orchestrator Deployment (N replicas)
  ├── K8s Service (ClusterIP) ← Runner/Envoy 连接入口
  ├── Redis 协调 (bridge/inbox/xds:notify)
  └── 节点感知 xDS 过滤

Envoy DaemonSet (每节点一个)
  ├── ADS → Orchestrator Service
  ├── node.id = NODE_NAME (节点感知)
  └── hostPath UDS ← Sandbox Pod egress

NetworkPolicy
  ├── Sandbox: deny-all, 只允许 Orchestrator + DNS
  └── Envoy: 允许外网 443/80
```
