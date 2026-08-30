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

**2. DB / Redis / 凭据加密配置** (`joysafeter-secrets-{env}`)

Orchestrator 从 `POSTGRES_*` / `REDIS_*` 拆分字段组装连接串（密码内部自动
URL-encode，无需手动处理 `@#!`）。新部署使用
`JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING` 与
`JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID`；只有仍含 `enc:`/`enc:v1:` 数据的旧部署才临时保留
`JOYSAFETER_VAULT_ENCRYPTION_KEY`。切流前必须初始化数据库 canary。

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
  --from-literal=JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID=active-2026-08

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
  --from-literal=JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID=active-2026-08
```

> 云 Redis/PG 走 TLS 时，追加 `--from-literal=REDIS_SCHEME=rediss` /
> `--from-literal=POSTGRES_SSLMODE=require`。

values 文件里只保留两处**引用名**（非敏感）：
- `externalSecret: joysafeter-secrets-{env}` — DB/Redis/Vault Secret
- `image.imagePullSecrets: [aisec-repo-cred]` — 仓库拉取凭证；chart 同时注入 Orchestrator、Envoy 和动态 sandbox Pod

### 1. Helm 部署

优先通过统一入口部署。下面命令从 `deploy/image-components.tsv` 投影 orchestrator 和四个独立 runtime
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

```bash
cd deploy/helm/joysafeter-orchestrator

# 预发
helm install joysafeter-pre . -f values-pre.yaml -n joysafeter-pre

# 生产
helm install joysafeter-prod . -f values-prod.yaml -n joysafeter-prod
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
helm upgrade joysafeter-pre . -f values-pre.yaml -n joysafeter-pre
helm upgrade joysafeter-prod . -f values-prod.yaml -n joysafeter-prod
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
| `joysafeter-secrets-{env}` | `POSTGRES_SSLMODE` | 可选, 强制 SSL 时 `require` |
| `joysafeter-secrets-{env}` | `JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING` | 当前及回滚窗口内读 key 的 JSON 映射 |
| `joysafeter-secrets-{env}` | `JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID` | 新写入使用的 key ID |
| `joysafeter-secrets-{env}` | `JOYSAFETER_VAULT_ENCRYPTION_KEY` | 仅用于读取尚未重包裹的 `enc:`/`enc:v1:` 历史密文 |
| `joysafeter-secrets-{env}` | `STORAGE_OSS_BUCKET/STORAGE_OSS_ENDPOINT/STORAGE_OSS_REGION` | OSS 连接参数；也可放 `orchestrator.storage.oss` |
| `joysafeter-secrets-{env}` | `STORAGE_OSS_ACCESS_KEY/STORAGE_OSS_SECRET_KEY` | OSS 凭证；线上推荐放 Secret |
| `joysafeter-secrets-{env}` | `STORAGE_S3_BUCKET/STORAGE_S3_ENDPOINT/STORAGE_S3_REGION` | S3 连接参数；也可放 `orchestrator.storage.s3` |
| `joysafeter-secrets-{env}` | `STORAGE_S3_ACCESS_KEY/STORAGE_S3_SECRET_KEY` | S3 凭证；使用 S3 时配置 |
| `aisec-repo-cred` | `.dockerconfigjson` | 私有仓库拉取凭证 |

> Deployment 通过 `envFrom.secretRef` 注入 `joysafeter-secrets-{env}` 的全部 key，
> 通过 `imagePullSecrets` 引用 `aisec-repo-cred`；动态创建的 sandbox Pod 也会直接带上同一列表，
> 不再依赖人工 patch namespace 的 `default` ServiceAccount。

### 非敏感配置 (values.yaml)

通过 `values-pre.yaml` / `values-prod.yaml` 覆盖：

| 参数 | 默认 | 说明 |
|------|------|------|
| `haMode` | `multi` | HA 模式: standalone/leader/multi |
| `orchestrator.replicas` | 3 | Orchestrator 副本数 |
| `orchestrator.pool.minSize` | 5 | 预热池最小沙箱数 |
| `orchestrator.sandbox.idleTimeout` | 300 | 沙箱空闲超时(秒) |
| `orchestrator.storage.backend` | `local` | 文件存储后端: local/s3/oss；线上推荐 oss/s3 |
| `orchestrator.storage.local.path` | `/data/files` | local 后端路径；启用 persistence 时挂 PVC |
| `orchestrator.storage.oss.bucket/endpoint/region` | 空/空/空 | OSS 非敏感参数；region 为空时不注入环境变量 |
| `orchestrator.storage.s3.bucket/endpoint/region` | 空/空/空 | S3 非敏感参数；region 允许为空字符串 |
| `envoy.socketHostDir` | `/data/joysafeter/envoy-sockets` | Envoy UDS hostPath |
| `envoy.runAsUser/runAsGroup` | `101/101` | Envoy 进程身份；初始化容器据此设置 socket 根目录所有权 |
| `egress.allowedHosts` | [见 values.yaml] | Envoy 出站白名单 |

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
| replicas | 1 | 3 |
| pool.minSize | 2 | 10 |
| sandbox.idleTimeout | 120s | 300s |
| sandbox.hardTimeout | 1h | 6h |
| logLevel | debug | info |
| orchestrator.storage.backend | s3 | s3 |
| envoy.socketHostDir | `/data/joysafeter-pre/...` | `/data/joysafeter-prod/...` |
| DB/Redis | pre 云实例 | prod 云实例 |

## 架构

```
Orchestrator Deployment (N replicas)
  ├── K8s Service (ClusterIP) ← Runner/Envoy 连接入口
  ├── Redis 协调 (bridge/inbox + network-policy generation 唤醒)
  └── 单一 Lease authority 发布节点感知 xDS

Envoy DaemonSet (每节点一个)
  ├── ADS → 当前 authority Service
  ├── node.id = NODE_NAME (节点感知)
  └── hostPath UDS ← Sandbox Pod egress

PostgreSQL
  └── 网络策略 generation/status 持久化真相；Redis 不保存 xDS 状态

NetworkPolicy
  ├── Sandbox: deny-all, 只允许 Orchestrator + DNS
  └── Envoy: 允许外网 443/80
```
