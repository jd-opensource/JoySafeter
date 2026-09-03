# JoySafeter Orchestrator Helm Chart

## 环境隔离与发布保护

dev、pre、prod 必须使用三个独立 namespace、Helm release、外部 Secret 和镜像锁文件。
`values.schema.json` 会拒绝 pre/production 中的
`:latest` 和无 tag 镜像。三个环境分别使用 `dev`、`pre`、`prod` 镜像通道：

```bash
images-dev.lock.yaml
images-pre.lock.yaml
images-prod.lock.yaml
```

`values-dev.yaml`、`values-pre.yaml`、`values-prod.yaml` 分别隔离 Redis 实例与 key 前缀、
event stream、外部 Secret 和 Envoy socket 目录。三个环境禁止共用 Redis 实例；独立 key
前缀是防止端点误配造成数据串扰的第二道保护。dev/pre 创建 ResourceQuota，prod 不设置集群资源上限。当前采用
管理员 kubeconfig 手工执行 Helm，不创建额外的集群内发布身份：

```bash
helm upgrade --install joysafeter-dev . \
  -n joysafeter-dev --create-namespace -f values-dev.yaml -f images-dev.lock.yaml
helm upgrade --install joysafeter-pre . \
  -n joysafeter-pre --create-namespace -f values-pre.yaml -f images-pre.lock.yaml
helm upgrade --install joysafeter-prod . \
  -n joysafeter-prod --create-namespace -f values-prod.yaml -f images-prod.lock.yaml
```

dev/pre 当前不设置节点选择器，可由调度器使用集群中的可用节点，但仍通过各自 namespace
的 ResourceQuota 限制资源数量；prod 同样不限制节点，并保持更高的调度优先级。

prod 使用集群级 `joysafeter-production` PriorityClass，在集群资源不足时可以抢占低优先级
dev/pre 工作负载。该资源由独立的 `joysafeter-platform` Helm release 统一管理，不归任何
单个环境 release 管理：

```bash
helm upgrade --install joysafeter-platform ../joysafeter-platform \
  --namespace joysafeter-system --create-namespace
```

dev/pre 的 ResourceQuota 当前限制 namespace 对象数量；prod 不创建 ResourceQuota。
在所有动态 sandbox 和 initContainer 都具备 requests/limits 前，不要直接增加 CPU/内存
强制配额。

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

**2. DB / Redis / 凭据加密配置** (`joysafeter-secrets-{env}`)

Orchestrator 从 `POSTGRES_*` / `REDIS_*` 拆分字段组装连接串（密码内部自动
URL-encode，无需手动处理 `@#!`）。新部署使用
`JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING` 与
`JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID`；只有仍含 `enc:`/`enc:v1:` 数据的旧部署才临时保留
`JOYSAFETER_VAULT_ENCRYPTION_KEY`。切流前必须初始化数据库 canary。

dev、pre、prod 的 `REDIS_HOST` 必须分别指向三套独立 Redis，不能只依赖不同
`REDIS_DB` 或 key prefix 进行隔离：

| 环境 | Secret | Redis |
|------|--------|-------|
| dev | `joysafeter-secrets-dev` | `redis-xxx-dev...` |
| pre | `joysafeter-secrets-pre` | `redis-xxx-pre...` |
| prod | `joysafeter-secrets-prod` | `redis-xxx-prod...` |

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
  --from-literal=JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING='{"active-2026-08":"<32-byte-base64-key>"}' \
  --from-literal=JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID=active-2026-08 \
  --from-literal=JOYSAFETER_XDS_AUTH_KEYRING='{"active":"<URL-safe-random-token>"}' \
  --from-literal=JOYSAFETER_XDS_AUTH_WRITE_KEY_ID=active \
  --from-literal=JOYSAFETER_XDS_AUTH_TOKEN='<same token selected by active>' \
  --from-literal=JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN='<independent random token>' \
  --from-literal=JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN='<independent random token>'

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
  --from-literal=JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING='{"active-2026-08":"<32-byte-base64-key>"}' \
  --from-literal=JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID=active-2026-08 \
  --from-literal=JOYSAFETER_XDS_AUTH_KEYRING='{"active":"<URL-safe-random-token>"}' \
  --from-literal=JOYSAFETER_XDS_AUTH_WRITE_KEY_ID=active \
  --from-literal=JOYSAFETER_XDS_AUTH_TOKEN='<same token selected by active>' \
  --from-literal=JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN='<independent random token>' \
  --from-literal=JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN='<independent random token>'
```

> 云 Redis 走 TLS 时，追加 `--from-literal=REDIS_SCHEME=rediss`。PostgreSQL
> 需要 TLS 时请改用带 `sslmode=require` 查询参数的 `DATABASE_URL`，不要同时配置
> `POSTGRES_*` 拆分字段。

Helm 固定使用独立 Agent Gateway，因此同一个 `externalSecret` 必须包含：

```text
JOYSAFETER_XDS_AUTH_KEYRING={"active":"<URL-safe-random-token>"}
JOYSAFETER_XDS_AUTH_WRITE_KEY_ID=active
JOYSAFETER_XDS_AUTH_TOKEN=<与 keyring 中 active 对应的 token>
JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN=<独立的 32-512 字节随机 Bearer token>
JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN=<独立的 32-512 字节随机 replica token>
```

xDS、management 与 replica token 用于不同信任边界，必须分别生成、不得复用。Gateway 不需要
数据库 URL 或业务凭证加密 key；Orchestrator PostgreSQL + vault 是唯一持久真相。

values 文件里只保留两处**引用名**（非敏感）：
- `externalSecret: joysafeter-secrets-{env}` — DB/Redis/Vault Secret
- `image.imagePullSecrets: [aisec-repo-cred]` — 仓库拉取凭证；chart 同时注入 Orchestrator、Envoy 和动态 sandbox Pod

### 1. Helm 部署

优先通过统一入口部署。下面命令从 `deploy/image-components.tsv` 投影 Agent Gateway、orchestrator 和四个独立 runtime
镜像，避免构建脚本与 Helm values 分别维护镜像名称：

```bash
cd deploy
./deploy.sh --registry aisec-repo.jd.com/joysafeter --tag <release-tag> \
  k8s deploy --sync-images --namespace joysafeter-pre \
  --release joysafeter-pre --values helm/joysafeter-orchestrator/values-pre.yaml

# 已存在 release，仅替换为本次统一 Registry 中的镜像
./deploy.sh --registry aisec-repo.jd.com/joysafeter --tag <release-tag> \
  k8s deploy --sync-images --reuse-values \
  --namespace joysafeter-pre --release joysafeter-pre
```

不传 `--sync-images` 时，chart 继续使用 values 文件中的镜像。直接调用 Helm 仅用于需要完全手工控制
values 的运维场景：

namespace 只由 Helm 的 `--namespace` / `-n` 决定。模板使用 `.Release.Namespace` 生成资源 metadata、
集群内 Service FQDN 和 `JOYSAFETER_K8S_NAMESPACE`，不要在 values 文件中再定义 namespace。

```bash
cd deploy/helm/joysafeter-orchestrator

# 预发
helm upgrade --install joysafeter-pre . \
  -f values-pre.yaml -f images-pre.lock.yaml -n joysafeter-pre

# 生产
helm upgrade --install joysafeter-prod . \
  -f values-prod.yaml -f images-prod.lock.yaml -n joysafeter-prod
```

### 2. 升级

`20260815_000001_normalize_credential_envelopes` 和
`20260815_000002_normalize_credential_public_ids` 都是 online-only 且不可逆的
凭据规范化迁移。升级前必须确认数据库备份可恢复，并确认
`JOYSAFETER_VAULT_ENCRYPTION_KEY` 与旧环境使用的是同一把密钥。不得生成新密钥
覆盖旧值。

迁移期间必须停止 API、worker、orchestrator 和所有旧 HA 实例，避免旧进程在
最终检查后重新写入 bare `enc:` 密文、裸 UUID 或旧凭据名称。使用目标环境的 DB
Secret 和 Vault Key 执行迁移：

```bash
cd backend
alembic upgrade head
alembic current  # 必须已应用 20260815_000002（镜像更新时 head 可为更晚版本）
```

迁移会在写入前验证全部 `enc:` / `enc:v1:` 密文；任意错误密钥、损坏密文、
未知 envelope 或非字符串 credential 值都会使整个事务回滚。迁移成功后，在
恢复流量前执行不暴露凭据内容的结构检查：

```sql
WITH credential_values AS (
    SELECT
        jsonb_typeof(item.value) AS json_type,
        CASE WHEN jsonb_typeof(item.value) = 'string' THEN item.value #>> '{}' END AS value
    FROM joysafeter_credentials c
    CROSS JOIN LATERAL jsonb_each(c.data) AS item(key, value)
), oauth_values AS (
    SELECT
        jsonb_typeof(item.value) AS json_type,
        CASE WHEN jsonb_typeof(item.value) = 'string' THEN item.value #>> '{}' END AS value
    FROM joysafeter_credentials c
    CROSS JOIN LATERAL jsonb_each(c.oauth_config) AS item(key, value)
    WHERE c.oauth_config IS NOT NULL
      AND item.key IN ('client_secret', 'refresh_token')
), violations AS (
    SELECT 'credentials.data' AS store FROM credential_values
    WHERE json_type <> 'string' OR (value <> '' AND value NOT LIKE 'enc:v1:%')
    UNION ALL
    SELECT 'credentials.oauth_config' FROM oauth_values
    WHERE json_type <> 'string' OR (value <> '' AND value NOT LIKE 'enc:v1:%')
    UNION ALL
    SELECT 'session_repos.encrypted_token' FROM joysafeter_session_repos
    WHERE encrypted_token <> '' AND encrypted_token NOT LIKE 'enc:v1:%'
    UNION ALL
    SELECT 'task_identity.encrypted_credential' FROM joysafeter_task_identity_contexts
    WHERE encrypted_credential IS NOT NULL
      AND encrypted_credential <> ''
      AND encrypted_credential NOT LIKE 'enc:v1:%'
)
SELECT store, count(*) AS violations FROM violations GROUP BY store;
```

查询必须返回 0 行。随后验证环境、会话快照和 agent-version 快照内的所有凭据引用
均为可解析、同项目且 kind 正确；当前环境、活跃会话和 agent-version 还必须指向
live 凭据，已终止或归档的历史会话允许保留已归档/删除凭据的稳定 public ID：

```sql
WITH snapshots AS (
    SELECT
        'sessions.agent_snapshot'::text AS source,
        s.id::text AS owner_id,
        s.project_id,
        s.agent_snapshot AS snapshot,
        (s.archived_at IS NULL AND s.status <> 'terminated') AS require_live
    FROM joysafeter_sessions s
    WHERE s.agent_snapshot IS NOT NULL
    UNION ALL
    SELECT
        'agent_versions.snapshot',
        v.id::text,
        a.project_id,
        v.snapshot,
        true
    FROM joysafeter_agent_versions v
    JOIN joysafeter_agents a ON a.id = v.agent_id
), environment_configs AS (
    SELECT
        'environments.config'::text AS source,
        e.id::text AS owner_id,
        e.project_id,
        e.config,
        true AS require_live
    FROM joysafeter_environments e
    WHERE e.config IS NOT NULL
    UNION ALL
    SELECT
        source || '.environment.config',
        owner_id,
        project_id,
        snapshot #> '{environment,config}',
        require_live
    FROM snapshots
    WHERE snapshot #> '{environment,config}' IS NOT NULL
), shape_violations AS (
    SELECT source, owner_id, 'environment config is not an object' AS reason
    FROM environment_configs
    WHERE jsonb_typeof(config) <> 'object'
    UNION ALL
    SELECT source || '.secret_refs', owner_id, 'secret_refs is not an array'
    FROM environment_configs
    WHERE config ? 'secret_refs'
      AND jsonb_typeof(config->'secret_refs') <> 'array'
    UNION ALL
    SELECT source || '.egress_services', owner_id, 'egress_services is not an array'
    FROM environment_configs
    WHERE config ? 'egress_services'
      AND jsonb_typeof(config->'egress_services') <> 'array'
    UNION ALL
    SELECT source || '.egress_services[' || (service.ordinality - 1) || ']', owner_id,
           'egress service is not an object'
    FROM environment_configs
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(config->'egress_services') = 'array'
             THEN config->'egress_services' ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS service(value, ordinality)
    WHERE jsonb_typeof(service.value) <> 'object'
    UNION ALL
    SELECT source || '.secret_ref', owner_id, 'legacy secret_ref key still exists'
    FROM snapshots
    WHERE snapshot ? 'secret_ref'
), refs AS (
    SELECT
        source || '.secret_refs[' || (ref.ordinality - 1) || ']' AS path,
        owner_id,
        project_id,
        require_live,
        'service'::text AS expected_kind,
        ref.value
    FROM environment_configs
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(config->'secret_refs') = 'array'
             THEN config->'secret_refs' ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS ref(value, ordinality)
    UNION ALL
    SELECT
        source || '.egress_services[' || (service.ordinality - 1) || '].service_credential_id',
        owner_id,
        project_id,
        require_live,
        'service',
        service.value->'service_credential_id'
    FROM environment_configs
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(config->'egress_services') = 'array'
             THEN config->'egress_services' ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS service(value, ordinality)
    WHERE jsonb_typeof(service.value) = 'object'
    UNION ALL
    SELECT
        source || '.model_credential_id',
        owner_id,
        project_id,
        require_live,
        'model',
        snapshot->'model_credential_id'
    FROM snapshots
    WHERE snapshot ? 'model_credential_id'
      AND snapshot->'model_credential_id' <> 'null'::jsonb
      AND COALESCE(snapshot->>'model_credential_id', '') <> ''
), resolved_refs AS (
    SELECT
        refs.*,
        CASE
            WHEN jsonb_typeof(value) = 'string'
             AND value #>> '{}' ~ '^cred_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            THEN substring(value #>> '{}' FROM 6)::uuid
        END AS credential_uuid
    FROM refs
), reference_violations AS (
    SELECT
        r.path AS source,
        r.owner_id,
        CASE
            WHEN r.value IS NULL THEN 'credential reference is missing'
            WHEN jsonb_typeof(r.value) <> 'string' THEN 'credential reference is not a string'
            WHEN r.credential_uuid IS NULL THEN 'credential reference is not canonical cred_<uuid>'
            WHEN c.id IS NULL THEN 'credential does not exist'
            WHEN c.project_id IS DISTINCT FROM r.project_id THEN 'credential belongs to another project'
            WHEN c.kind <> r.expected_kind THEN 'credential has the wrong kind'
            WHEN r.require_live
             AND (c.archived_at IS NOT NULL OR c.deleted_at IS NOT NULL)
            THEN 'credential is not live'
        END AS reason
    FROM resolved_refs r
    LEFT JOIN joysafeter_credentials c ON c.id = r.credential_uuid
    WHERE r.value IS NULL
       OR jsonb_typeof(r.value) <> 'string'
       OR r.credential_uuid IS NULL
       OR c.id IS NULL
       OR c.project_id IS DISTINCT FROM r.project_id
       OR c.kind <> r.expected_kind
       OR (r.require_live AND (c.archived_at IS NOT NULL OR c.deleted_at IS NOT NULL))
)
SELECT source, owner_id, reason FROM shape_violations
UNION ALL
SELECT source, owner_id, reason FROM reference_violations
ORDER BY source, owner_id;
```

这组查询也必须返回 0 行。之后再升级并启动 orchestrator/API：

```bash
helm upgrade joysafeter-pre . \
  -f values-pre.yaml -f images-pre.lock.yaml -n joysafeter-pre
helm upgrade joysafeter-prod . \
  -f values-prod.yaml -f images-prod.lock.yaml -n joysafeter-prod
```

验证 credential 列表读取及代表性 runner 注入后，再扩容其他实例。曾以明文落库
的 API Key、Auth Token 必须在迁移完成后轮换。

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
| `joysafeter-secrets-{env}` | `JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING` | 当前及回滚窗口内读 key 的 JSON 映射 |
| `joysafeter-secrets-{env}` | `JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID` | 新写入使用的 key ID |
| `joysafeter-secrets-{env}` | `JOYSAFETER_VAULT_ENCRYPTION_KEY` | 仅用于读取尚未重包裹的 `enc:`/`enc:v1:` 历史密文 |
| `joysafeter-secrets-{env}` | `JOYSAFETER_XDS_AUTH_KEYRING/JOYSAFETER_XDS_AUTH_WRITE_KEY_ID/JOYSAFETER_XDS_AUTH_TOKEN` | Envoy ADS token keyring、当前写 key 和当前 token |
| `joysafeter-secrets-{env}` | `JOYSAFETER_AGENT_GATEWAY_MANAGEMENT_TOKEN` | Orchestrator 调用独立 Gateway 管理 API 的 Bearer token |
| `joysafeter-secrets-{env}` | `JOYSAFETER_AGENT_GATEWAY_REPLICATION_TOKEN` | Gateway 副本间快照、增量和 ACK 的独立 Bearer token |
| `joysafeter-secrets-{env}` | `STORAGE_OSS_BUCKET/STORAGE_OSS_ENDPOINT/STORAGE_OSS_REGION` | OSS 连接参数；也可放 `orchestrator.storage.oss` |
| `joysafeter-secrets-{env}` | `STORAGE_OSS_ACCESS_KEY/STORAGE_OSS_SECRET_KEY` | OSS 凭证；线上推荐放 Secret |
| `joysafeter-secrets-{env}` | `STORAGE_S3_BUCKET/STORAGE_S3_ENDPOINT/STORAGE_S3_REGION` | S3 连接参数；也可放 `orchestrator.storage.s3` |
| `joysafeter-secrets-{env}` | `STORAGE_S3_ACCESS_KEY/STORAGE_S3_SECRET_KEY` | S3 凭证；使用 S3 时配置 |
| `aisec-repo-cred` | `.dockerconfigjson` | 私有仓库拉取凭证 |

`SECRET_KEY` 属于 Python API，不应放入 Orchestrator/Gateway 的 Secret；
`JWT_SECRET_KEY` 是已删除的旧别名，不要配置。`JOYSAFETER_VAULT_ENCRYPTION_KEY`
不是新环境 token，仅在仍需读取 `enc:`/`enc:v1:` 历史密文时保留原值。

> Orchestrator Deployment 通过 `envFrom.secretRef` 注入 `joysafeter-secrets-{env}` 的全部 key；Agent Gateway
> 只按 key 引用 xDS/management/replication token，不会继承数据库、Redis、vault、存储或其他业务凭证。
> 各工作负载通过 `imagePullSecrets` 引用 `aisec-repo-cred`；动态创建的 sandbox Pod 也会直接带上同一列表，
> 不再依赖人工 patch namespace 的 `default` ServiceAccount。

### 非敏感配置 (values.yaml)

通过 `values-pre.yaml` / `values-prod.yaml` 覆盖：

| 参数 | 默认 | 说明 |
|------|------|------|
| `orchestrator.replicas` | 3 | Orchestrator 副本数 |
| `agentGateway.replicas` | 3 | Gateway 副本数；ADS/管理面 Lease 主备，策略热快照复制 |
| `agentGateway.nodeVisibility` | `node_scoped` | 节点感知投递；也可设为 `unscoped` |
| `agentGateway.leaderLeaseDurationSeconds` | `15` | ADS/管理 authority 的 Lease 时长 |
| `agentGateway.leaderRenewIntervalSeconds` | `5` | Lease 续约间隔，必须小于 Lease 时长 |
| `agentGateway.kubernetesApiCidrs` | `[]` | 标准 NetworkPolicy 下必须配置的 Kubernetes API CIDR；Cilium 不需要 |
| `agentGateway.podAnnotations` | `{}` | service mesh sidecar 注入等 Pod 注解；生产 mTLS 由 mesh 强制 |
| `agentGateway.deliveryTimeoutSeconds` | `20` | 管理请求等待共享 Envoy ACK/NACK 的上限 |
| `agentGateway.requestTimeoutSeconds` | `25` | Orchestrator 调用 Gateway 的整个重试操作超时；必须覆盖投递、复制 ACK 和传输余量，并小于 Orchestrator 的 30 秒策略上限 |
| `agentGateway.shutdownGraceSeconds` | `10` | SIGTERM 后停止接流并排空现有 HTTP/gRPC 请求的上限 |
| `agentGateway.podDisruptionBudget.maxUnavailable` | `1` | 计划内驱逐时最多不可用 Gateway 副本数 |
| `orchestrator.pool.minSize` | 5 | 预热池最小沙箱数 |
| `orchestrator.sandbox.idleTimeout` | 300 | 沙箱空闲超时(秒) |
| `orchestrator.storage.backend` | `local` | 文件存储后端: local/s3/oss；线上推荐 oss/s3 |
| `orchestrator.storage.local.path` | `/data/files` | local 后端路径；启用 persistence 时挂 PVC |
| `orchestrator.storage.oss.bucket/endpoint/region` | 空/空/空 | OSS 非敏感参数；region 为空时不注入环境变量 |
| `orchestrator.storage.s3.bucket/endpoint/region` | 空/空/空 | S3 非敏感参数；region 允许为空字符串 |
| `agentIdentity.provider` | `none` | 设为 `jd` 时，Helm 发布前要求 `baseUrl`、`clientId`、`platformId`；`clientSecret` 仍由 `externalSecret` 提供 |
| `agentIdentity.services` | `[]` | 当前 namespace 的 Agent Identity 信任目标；支持精确域名与仅位于开头的 `*.example.com` 通配符，修改 CR 后无需重启 Orchestrator |
| `envoy.socketHostDir` | `/data/joysafeter/envoy-sockets` | Envoy UDS hostPath |
| `envoy.runAsUser/runAsGroup` | `101/101` | Envoy 进程身份；初始化容器据此设置 socket 根目录所有权 |
| `envoy.terminationGracePeriodSeconds/envoy.drainSeconds` | `40/20` | Envoy 退出总宽限期与 listener 主动排空时间；前者必须更大 |
| `egress.allowedHosts` | [见 values.yaml] | Envoy 出站白名单 |

Agent Identity 信任目标可随应用 release 声明，例如：

```yaml
agentIdentity:
  provider: jd
  baseUrl: "https://beta-idsc.jd.com"
  clientId: "<client-id>"
  platformId: "<platform-id>"
  services:
    - name: icc-dataagent-http
      host: icc-dataagent-api.jd.com
      port: 80
      tls: false
    - name: trusted-dataagents-https
      host: "*.dataagent.jd.com"
      port: 443
      tls: true
```

也可以直接修改当前 namespace 的 CR；每个 Orchestrator 副本都会 List/Watch，并原子替换
内存快照，不需要重启。首次同步完成前实例不会 Ready；空快照合法，但身份注入会 fail-closed。
`*.dataagent.jd.com` 可以匹配 `api.dataagent.jd.com` 和更深层子域，但不会匹配
`dataagent.jd.com`。CR 同时绑定 provider、host、port 与 TLS，不能只靠域名放宽协议。

动态 sandbox Pod 的 initContainer 负责在 `envoy.socketHostDir` 下创建 UUID 子目录；Pod 停止或销毁后，
Kubernetes provider 会通过同节点 Envoy DaemonSet Pod 清理该目录。Chart 的 `pods/exec` RBAC 是该节点
文件生命周期能力的一部分，不代表 provider 可以修改 xDS authority 或资源状态。

Envoy DaemonSet 的 root initContainer 只负责幂等初始化 hostPath 根目录：临时收回为 root、收紧为
`0750`，再交给 `envoy.runAsUser/runAsGroup`。它丢弃全部 capabilities 后仅加回执行 `chown` 所需的
`CHOWN`；主 Envoy 容器始终以非 root UID/GID 运行并丢弃全部 capabilities。

### 预发 vs 生产差异

| 参数 | 预发 (pre) | 生产 (prod) |
|------|------|------|
| namespace | `joysafeter-pre` | `joysafeter-prod` |
| orchestrator.replicas | 2 | 3 |
| agentGateway.replicas | 2 | 3 |
| pool.minSize | 2 | 10 |
| sandbox.idleTimeout | 120s | 300s |
| sandbox.hardTimeout | 1h | 6h |
| logLevel | debug | info |
| orchestrator.storage.backend | s3 | s3 |
| envoy.socketHostDir | `/data/joysafeter-pre/...` | `/data/joysafeter-prod/...` |
| DB/Redis | pre 云实例 | prod 云实例 |

## 架构

```text
Orchestrator Deployment (N replicas)
  ├── K8s Service (ClusterIP) ← Runner 连接入口
  ├── Redis 协调 (bridge/inbox + network-policy generation 唤醒)
  ├── PostgreSQL 权威策略状态
  └── 管理 API → Agent Gateway（固定 multi，无 K8s leader）

Agent Gateway Deployment (N replicas, RollingUpdate)
  ├── leader-only Service: management HTTP + authenticated Delta ADS
  ├── K8s Lease + epoch: 单写者与旧主 fencing
  └── 内存 xDS 投影 + 完整策略热快照；无 DB/vault/Redis 权限

Envoy DaemonSet (每节点一个)
  ├── ADS → Agent Gateway
  ├── node.id = NODE_NAME (节点感知)
  └── hostPath UDS ← Sandbox Pod egress

PostgreSQL
  └── 网络策略 generation/status 持久化真相（仅 Orchestrator 访问）

Orchestrator vault
  └── 业务凭证唯一持久副本；发布策略时解析并通过认证管理面下发

NetworkPolicy
  ├── Sandbox: deny-all, 只允许 Orchestrator + DNS
  └── Envoy: 允许外网 443/80
```

独立模式下，Lease leader 以 `(boot_id, lease epoch)` 标识当前 authority。Orchestrator 比较 Gateway
上报的 sandbox generation inventory，只把缺失/不匹配项通过正常的 `stage → publish → ACK → commit`
路径重放，prune 后调用 recovery complete。恢复阶段 Envoy 保留 last-good；Ready 后才精确删除未重放资源。
leader 失效时 standby 竞争 Lease，旧 epoch 的在途写全部失败关闭。新 leader 从完整热快照恢复，
并由 Orchestrator 按 PostgreSQL 权威代际进行校验和必要重放。

生产环境建议通过 `agentGateway.podAnnotations` 注入 Istio/Linkerd sidecar，并在 mesh 中对 Envoy ↔ Gateway
和 Gateway ↔ Orchestrator 开启严格 mTLS 与 workload identity。Chart 不替某一种 mesh 创建 CRD；token
认证仍作为纵深防御。标准 Kubernetes NetworkPolicy 场景必须显式配置
`agentGateway.kubernetesApiCidrs`，否则 Gateway 对 Kubernetes Lease API 的访问会被拒绝。
