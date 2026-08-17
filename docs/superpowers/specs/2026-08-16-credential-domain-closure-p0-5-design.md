# P0.5 Credential Domain Closure 与统一语言设计

- 日期：2026-08-16
- 状态：重写后待架构复审
- 基线：`joysafeter-v2-0814` @ `6a58bba205fad83640728906372d5bd7c9154f74`
- 前置：统一 Credential 数据骨干与 P1 管理体验已经落地
- 后续：`2026-08-16-sensitive-material-envelope-p0-6-design.md`
- 性质：领域、事务和运行时闭环；保留 `enc:v1`，不承诺密文上下文绑定

---

## 1. 决策摘要

P0 已经把 Secret、Vault Credential 和 MCP Vault 条目迁移到统一表，但系统尚未完成统一领域。当前代码仍把以下不同概念混在一起：

- 业务对象：项目管理员创建、绑定、归档和删除的 Credential。
- 敏感值：API key、token、client secret 等 Credential Material。
- 通用安全材料：Task Identity、Repository Token、部署密钥。
- 历史实现词：Secret、Vault、VaultCipher、secret refs。

P0.5 的核心决策是：

1. **Credential 是唯一的托管凭据业务名词。**
2. **Secret 不再是业务对象。** 它只允许出现在通用安全描述、外部产品名和 legacy 兼容代码中。
3. **Vault 不再是 Credential 容器。** 它只允许表示历史迁移来源或真正的外部密钥保管基础设施。
4. **Sensitive Material 是跨领域安全基础设施概念，不属于 Credential Domain。**
5. P0.5 完成业务语言、Binding Policy、Dependency/Impact、事务、Snapshot 和 Runtime Store 闭环。
6. P0.6 完成 `enc:v2`、purpose/AAD、Keyring 和按领域迁移；P0.5 不伪造这些密码学保证。

P0.5 不是一次全局字符串替换。正确顺序是先建立目标边界和 Adapter，再迁移调用方，最后删除活跃业务路径中的旧词并启用架构守卫。

---

## 2. 诚实的当前状态

### 2.1 已完成能力

- `joysafeter_credentials` 保存 `model`、`service`、`mcp` 三类项目级 Credential Resource。
- `joysafeter_credential_groups` 表达 MCP Credential 的动态授权集合。
- Agent、Trigger、Environment、Session 已经主要使用稳定 Credential ID。
- Python 写侧具备加密、脱敏、生命周期和部分依赖扫描。
- Rust 能从统一表解析模型、Service、MCP 及其他历史敏感材料。
- Credential mutation 与部分 Sandbox policy pending 标记已经可以同事务提交。
- `enc:v1` 已有 Python/Rust 交叉测试和版本前缀。
- 历史 Secret/Vault 数据迁移保留了活跃和非活跃数据。

### 2.2 当前立即阻断项

这些问题不是 P0.5 完成后的优化，而是进入预发前必须先收口的 P0.5-0：

1. Python/DB 使用 Credential kind `model`，Rust LLM Catalog 却要求 `llm`。
2. 历史 MCP `credential_type=bearer` 与新写侧 `static_bearer` 没有权威兼容映射。
3. Runtime 多处把“未配置”与“已配置但不存在、跨项目、归档或损坏”都处理为 `None`/跳过。
4. Runtime Store 接受可空 project scope，部分 SQL 在 project 为空时放宽过滤。
5. Session Snapshot 创建与 Credential archive/delete 存在 TOCTOU。

在 P0.5-0 通过前，不得宣称当前 Credential Runtime 已经跨语言自洽。

### 2.3 P0.5 不提供的安全保证

P0.5 继续使用 `enc:v1`。因此：

- 数据库只读泄露在攻击者没有运行时根密钥时仍不能直接恢复明文。
- AES-GCM 仍能检测随机篡改和错误 key。
- **相同根密钥下，密文没有绑定 project/resource/field/purpose。** 数据库写权限攻击者可能把合法密文复制到另一个上下文并继续解密。
- Managed Credential、Task Identity 和 Repository Material 仍可能共享历史 root key，但 P0.5 必须通过独立 Adapter 隔离调用边界。

跨 purpose 和跨资源抗搬移只在 P0.6 完成对应数据 contract 后成立。

---

## 3. 统一语言

### 3.1 权威术语

| 术语 | 定义 | 所属边界 |
|---|---|---|
| Credential Resource | 项目级、可复用、用户管理、有生命周期的托管凭据 | Managed Credentials |
| Credential Material | Credential Resource 持有的敏感字段集合 | Managed Credentials |
| Credential Group | MCP Credential 的项目级动态授权集合 | Managed Credentials |
| Credential Binding | 消费方对 Resource 或 Group 的显式引用及使用配置 | 消费方拥有，Policy 校验 |
| Credential Usage | Material 被怎样消费的领域枚举 | Managed Credentials |
| Credential Reference | 持久化配置或 Snapshot 中的 Credential/Group ID | 跨边界契约 |
| Sensitive Material | 需要可逆保护的通用安全值，不等同于 Credential | Shared Security Infrastructure |
| Material Purpose | P0.6 用于密码学分域的枚举 | Shared Security Infrastructure |

### 3.2 `Secret` 的允许范围

允许：

- Kubernetes Secret、Secret Manager 等外部产品正式名称。
- “不得把 secret 写入日志”这类通用安全描述。
- legacy migration、v0/v1 Decoder 和兼容 fixture 中的历史字段名。

禁止：

- 新业务模型、表、Service、API、错误码或 Runtime 类型使用 Secret 表示 Credential。
- 新字段继续写 `secret_ref`、`secret_refs`、`secret_key`。
- 用 Secret 同时指代 Credential Resource、Material 和部署密钥。

### 3.3 `Vault` 的允许范围

允许：

- 历史表、历史迁移来源及兼容测试。
- 真正的 External Vault/KMS/Secret Manager Adapter。
- `JOYSAFETER_VAULT_ENCRYPTION_KEY` 作为明确标记的 v1 legacy 配置，保留到 P0.6 contract。

禁止：

- 把 Credential Group、Credential Store 或 Material Protector 命名为 Vault。
- 新增 `VaultCredentialRow`、`VaultCipher`、`resolve_vault_credentials` 等活跃业务类型。

### 3.4 Legacy 隔离规则

旧词不能通过“历史兼容”无限扩散。所有保留旧词的代码必须满足至少一项：

- 位于 Alembic migration。
- 位于版本化 `legacy/v0/v1` Decoder。
- 位于迁移/兼容测试 fixture。
- 位于 legacy 配置读取 Adapter，且对外只暴露新语言。

架构测试只豁免明确目录和符号，不允许全局字符串白名单。

### 3.5 当前名称到目标名称

| 当前名称 | P0.5 目标 | 最终删除时点 |
|---|---|---|
| `SecretRow` | `CredentialRecord` | P0.5-D |
| `RuntimeSecretBinding` | `RuntimeCredentialBinding` | P0.5-D |
| `VaultCredentialRow` | `McpCredentialRecord` | P0.5-D |
| `resolve_vault_credentials` | `resolve_mcp_group_credentials` | P0.5-D |
| `VaultCipher` | `LegacyV1MaterialProtector` | 旧名 P0.5-D 删除；v1 实现到 P0.6 contract 才删除 |
| `CredentialCipher` 被其他领域直接调用 | 各领域 Purpose Adapter 调用共享 legacy v1 protector | P0.5-A |
| `secret_ref` | `model_credential_id` 或明确的 Credential Reference | 新写 P0.5-E2 停止；历史读取永久留在 legacy Decoder |
| `secret_refs` | `environment_credential_ids` | 新写 P0.5-E2 停止；历史读取永久留在 legacy Decoder |
| `secret_key` | `credential_field` | 新写 P0.5-E2 停止；历史读取永久留在 legacy Decoder |
| `JOYSAFETER_VAULT_ENCRYPTION_KEY` | P0.5 内部仅作为 `legacy_v1_key` 读取 | P0.6 R5 contract |

公开 API、Domain 类型和 Runtime 输出不得暴露 `LegacyV1` 实现名；它只属于安全基础设施 Adapter。

---

## 4. 边界上下文

| 边界 | 核心对象 | 是否为 Credential | P0.5 处理 |
|---|---|---:|---|
| Managed Credentials | Resource、Group、Binding、Usage | 是 | 完成领域闭环 |
| Task Identity Delegation | 单任务、短 TTL、一次消费的身份材料 | 否 | 独立 Adapter，禁止依赖 Credential Service |
| Repository Access | Session/Repository clone、push 凭据 | 否 | 独立 Adapter；暂不重构业务生命周期 |
| Identity Federation | Provider、Principal、Account Binding | 否 | 保持 token 不落库；不搭车删列 |
| Project Access | Project Access Token | 否 | 继续只存哈希 |
| Deployment Security | JWT、DB、Storage、root key | 否 | 由部署系统管理 |
| Shared Security Infrastructure | v1/v2 cipher、Keyring、Material Protector | 否 | P0.5 收口接口，P0.6 升级协议 |

反腐规则：

1. Task Identity 和 Repository Access 可以共享底层密码学库，但不能调用 Credential Domain Service。
2. Federation token 不得进入 Credential 表。
3. Deployment secret 不得成为 Credential kind。
4. Credential Domain 不读取 root key 环境变量，只依赖 Material Protection Port。
5. Identity Federation 模型清理由独立变更负责，不再塞入 P0.5 Credential 发布单元。

---

## 5. 目标与非目标

### 5.1 目标

1. Credential 的 kind、state、usage、binding 和 lifecycle 只有一个权威定义。
2. Python、Rust、Frontend 使用一致的 ID、字段和错误语义。
3. 所有持久化引用面可穷举，并区分 blocker、refresh impact 和历史证据。
4. Snapshot 创建和生命周期变更在线性化事务中互斥。
5. Runtime 对配置缺失和配置损坏采用不同的强类型结果。
6. 活跃业务代码不再使用 Secret/Vault 表示 Credential。
7. P0.5 每个切片可在明确 rollback floor 上滚动发布。
8. P0.6 获得唯一 Material Adapter、明确 purpose 边界和完整迁移表面。

### 5.2 非目标

- `enc:v2`、AAD、HKDF、Keyring、全库重加密。
- MCP OAuth Authorization Code/PKCE/callback/refresh。
- Trigger Credential Grant 新功能。
- Credential 跨项目共享或继承。
- Repository Access 生命周期重构。
- Identity Federation OAuthAccount 删列。
- External KMS/HSM。
- 把所有包含 token/key/secret 的数据迁入 Credential。

---

## 6. 分层与模块边界

```text
HTTP / Worker / Scheduler / gRPC
              │
              ▼
Credential Application
  - authorization context
  - transaction and locks
  - audit and impact coordination
  - repository/material ports
              │
              ▼
Credential Domain Core
  - resource metadata
  - state/usage/binding policies
  - dependency disposition
  - no framework imports
              ▲
              │ ports
Persistence / Security / Runtime / Audit / Refresh Adapters
```

### 6.1 Python 目标结构

```text
backend/app/joysafeter_domain/credentials/
  types.py
  resource.py
  material.py
  bindings.py
  policies.py
  lifecycle.py
  references.py
  dependencies.py

backend/app/joysafeter_application/credentials/
  resource_service.py
  group_service.py
  binding_service.py
  snapshot_service.py
  ports.py
  composition.py

backend/app/joysafeter_infrastructure/credentials/
  sqlalchemy_repository.py
  material_adapter.py
  dependency_scanners.py
  network_policy_adapter.py
  audit_adapter.py
```

若本轮不移动顶层目录，也必须通过 import guard 达到同样依赖方向。Audit、Redis refresh、事务和具体 Repository Port 属于 Application，不放进纯 Domain Core。

### 6.2 Rust 目标结构

```text
kernel/credentials/
  mod.rs
  store.rs
  record.rs
  material.rs
  error.rs
  model.rs
  service.rs
  mcp.rs
  reference.rs

kernel/task_identity/
  material.rs

kernel/repository_access/
  material.rs

kernel/sensitive_material/
  legacy_v1.rs
```

`harness_input_builder`、`sandbox_resolver` 和 `scheduler` 只能编排，不得自行查询 Credential 表或解密 Credential Material。

### 6.3 Reference Registry 的分层落位

Reference Registry 不能整体放进 Domain Core，也不能整体退化为 Infrastructure scanner 列表。

原因是它同时包含两类性质不同的对象：

- `ReferenceSurfaceDescriptor` 是纯领域元数据：surface id、surface kind、适用 operation、disposition、owner、是否持久化。
- `ReferenceScanner` 是 Application Port 的实现：它需要 SQLAlchemy、JSONB 查询、Snapshot Codec 或其他基础设施能力。

目标结构：

```python
@dataclass(frozen=True)
class ReferenceSurfaceDescriptor:
    surface_id: ReferenceSurfaceId
    kind: ReferenceSurfaceKind
    target: ReferenceTarget
    dispositions: frozenset[DependencyDisposition]
    scanner_id: ReferenceScannerId | None
    owner: str

class ReferenceScanner(Protocol):
    scanner_id: ReferenceScannerId

    async def scan_resource(
        self,
        project_id: ProjectId,
        credential_id: CredentialId,
    ) -> Sequence[CredentialDependency]: ...
```

- Descriptor 和 disposition 定义在 `joysafeter_domain/credentials/dependencies.py`。
- Scanner Port 定义在 `joysafeter_application/credentials/ports.py`。
- SQL/JSON/Snapshot scanner 实现在 `joysafeter_infrastructure/credentials/dependency_scanners.py`。
- `joysafeter_application/credentials/composition.py` 是唯一组装点；启动和测试时验证每个持久化 descriptor 恰有一个 scanner，ephemeral descriptor 必须显式使用 `NoPersistentDependencyScanner`。
- Domain Core 不保存 callable、Session、Repository 或 Infrastructure 实例。

仅有正向 Registry 不能证明穷举。失败构造如下：新增消费者直接保存 `credential_id`，但开发者既未注册 descriptor，也未实现 scanner；“所有已注册 descriptor 都完整”的测试仍然全绿，而 archive/delete 会漏判依赖。

因此必须同时建立反向普查：

1. 从 SQLAlchemy metadata 和 Alembic schema 中枚举 Credential/Group FK、typed-ID 列及关联表。
2. 从 `CredentialReferenceCodec` 声明中枚举全部 JSON/Snapshot key path；业务代码中的 reference key 字符串必须被 guard 禁止。
3. 对 Python/Rust raw SQL 做 AST/cfg-aware 守卫，枚举查询 Credential 表、Group 表及 reference 列的代码点。
4. 对 `decrypt`/`reveal` 调用点做守卫，Managed Credential 只允许 Material Adapter，Task Identity 和 Repository 只允许各自 Adapter。
5. 发现项必须分类为 registered surface、aggregate internal 或显式 exception；exception 必须包含 owner、理由和到期条件。

CI 中必须满足：

```text
reverse_census
  = registered_surfaces
  ∪ aggregate_internal_surfaces
  ∪ reviewed_exceptions
```

任一未分类发现项、无 scanner 的持久化 descriptor、无 descriptor 的 scanner 都使架构测试失败。

---

## 7. Domain Core

### 7.1 基础枚举

```python
class CredentialKind(StrEnum):
    MODEL = "model"
    SERVICE = "service"
    MCP = "mcp"

class CredentialState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"

class CredentialAuthScheme(StrEnum):
    STATIC_BEARER = "static_bearer"
    OAUTH2_LEGACY_DISABLED = "oauth2_legacy_disabled"

class CredentialUsage(StrEnum):
    MODEL_INFERENCE = "model_inference"
    WEBHOOK_AUTH = "webhook_auth"
    ENVIRONMENT_INJECTION = "environment_injection"
    HTTP_EGRESS = "http_egress"
    MCP_EGRESS = "mcp_egress"
```

跨语言唯一持久化值是 `model`，不得在 Rust 内另造 `llm` 作为 Credential kind。LLM 可以是产品/能力名称，不是 Resource kind。

### 7.2 Resource 不直接携带明文

```python
@dataclass(frozen=True)
class CredentialMaterialDescriptor:
    field_names: frozenset[CredentialFieldName]

@dataclass(frozen=True)
class CredentialResource:
    id: CredentialId
    project_id: ProjectId
    name: str
    kind: CredentialKind
    identity: CredentialIdentity
    material: CredentialMaterialDescriptor
    state: CredentialState
    is_default: bool
```

生命周期、依赖扫描、列表和大部分 Binding 校验不应解密材料。明文只通过 usage-scoped Material Port 显式加载。

### 7.3 Material 值对象

```python
@dataclass(frozen=True)
class SensitiveValue:
    _value: str

    def __repr__(self) -> str:
        return "SensitiveValue(<redacted>)"

    def reveal(self, capability: MaterialRevealCapability) -> str: ...

@dataclass(frozen=True)
class CredentialMaterial:
    fields: Mapping[CredentialFieldName, SensitiveValue]
```

构造时必须把输入复制为真正不可变映射，不能因 `frozen=True` 仍共享可变 dict。

通用限制：最多 50 字段；字段名 1–128 字符；单值最大 8192 字符；只允许平面字符串。Environment Injection 额外要求 POSIX env 名。MCP static bearer 必须包含 `token_value`。

`SensitiveValue`、Material、ciphertext、masked suffix 都不得进入 repr、日志、错误 data、Audit、事件、Snapshot 或 tracing field。

### 7.4 历史 Auth Scheme 映射

Persistence Mapper 必须支持：

| 持久化值 | Domain 值 | 行为 |
|---|---|---|
| `static_bearer` | `STATIC_BEARER` | 可运行 |
| `bearer` | `STATIC_BEARER` | legacy alias；只读兼容或受控 backfill |
| `oauth` / `mcp_oauth` | `OAUTH2_LEGACY_DISABLED` | 可读、不可创建、不可运行、不可 restore |
| 其他值 | corrupt row | fail closed |

P0.5 preflight 必须列出全部 distinct 值及资源 ID，不能假定只有测试中已知值。

---

## 8. Usage 与判别式 Binding Policy

单一万能 Binding Request 被拒绝，因为不同 Usage 需要不同上下文。

```python
@dataclass(frozen=True)
class ModelInferenceBinding:
    project_id: ProjectId
    credential_id: CredentialId
    engine_kind: EngineKind
    model_id: str | None

@dataclass(frozen=True)
class WebhookAuthBinding:
    project_id: ProjectId
    credential_id: CredentialId
    credential_field: CredentialFieldName
    methods: frozenset[WebhookAuthMethod]

@dataclass(frozen=True)
class EnvironmentInjectionBinding:
    project_id: ProjectId
    credential_id: CredentialId

@dataclass(frozen=True)
class HttpEgressBinding:
    project_id: ProjectId
    credential_id: CredentialId
    endpoint: NormalizedEndpoint
    inject: EgressInjectPolicy

@dataclass(frozen=True)
class McpGroupBinding:
    project_id: ProjectId
    group_ids: tuple[CredentialGroupId, ...]
    declared_server_urls: tuple[NormalizedMcpUrl, ...]
```

统一校验顺序：

1. project scope 必须存在且一致。
2. Resource/Group 存在且非 deleted。
3. state 允许当前操作。
4. Usage 与 kind 匹配。
5. identity/config 合法。
6. Material 字段存在。
7. Catalog、auth method、endpoint 和 URL 冲突规则通过。

Quickstart 和 Skill AI Authoring 属于 ephemeral `MODEL_INFERENCE` consumer。它们必须注册 Policy/Material Adapter，但使用显式 `NoPersistentDependencyScanner`，不能为了满足接口伪造持久化依赖。

---

## 9. Reference Surface、Dependency 与 Impact

### 9.1 Surface 分类

```python
class ReferenceSurfaceKind(StrEnum):
    AGGREGATE_INTERNAL = "aggregate_internal"
    LIVE_BINDING = "live_binding"
    HISTORICAL_EXECUTABLE = "historical_executable"
    ACTIVE_SNAPSHOT = "active_snapshot"
    EPHEMERAL_CONSUMER = "ephemeral_consumer"
    LEGACY_COMPATIBILITY = "legacy_compatibility"
```

Credential→Group ownership FK 属于 aggregate internal，不是外部 consumer。正向 Registry 与反向普查必须按分类对账，而不是要求所有 FK 都对应 Consumer Descriptor。

### 9.2 Operation-specific disposition

```python
class DependencyDisposition(StrEnum):
    BLOCK_RESOURCE_ARCHIVE = "block_resource_archive"
    BLOCK_RESOURCE_DELETE = "block_resource_delete"
    BLOCK_GROUP_ARCHIVE = "block_group_archive"
    BLOCK_GROUP_DELETE = "block_group_delete"
    REFRESH_RUNTIME_POLICY = "refresh_runtime_policy"
    REVALIDATE_ON_ACTIVATION = "revalidate_on_activation"
    AUDIT_ONLY = "audit_only"
```

Dependency 不能再只有 `in_use: bool`。

### 9.3 必须登记的 surface

- Live Agent model binding。
- Agent Version executable snapshot。
- Trigger webhook auth binding。
- Live Environment direct injection 与 HTTP egress binding。
- Active Session model/environment snapshot。
- Session→Credential Group association。
- Quickstart 和 Skill AI Authoring ephemeral consumer。
- legacy v0/v1 Environment/Snapshot key paths。

### 9.4 MCP 动态语义

- Session→Group 对 Group archive/delete 是 blocker。
- Session→Group 对 member add/archive/delete 是 refresh impact，不阻止成员变化。
- MCP member 不因为 Group 被 Session 绑定就自动成为 Resource lifecycle blocker。
- member 变化必须重新检查绑定 Session 之间的 normalized URL 冲突并持久化 policy pending。
- Group archive 不级联 archive member。

### 9.5 Agent Version 裁决

Agent Version Snapshot 是历史可执行配置，但不永久阻止 Credential 生命周期，否则历史版本会无限冻结 Credential。

裁决：

- Agent Version surface 使用 `REVALIDATE_ON_ACTIVATION`。
- 创建 pinned-version Session 时，必须重新解析 Snapshot 中全部 Credential Reference，并执行当前 Policy。
- 失效引用返回明确错误，不创建 Session。
- 已经创建的 active Session Snapshot 才是生命周期 blocker。

---

## 10. 生命周期与并发

### 10.1 Resource 状态机

```text
ACTIVE ──archive──> ARCHIVED ──restore──> ACTIVE
  │                    │
  └────delete──────────┴────delete──────> DELETED
```

- ARCHIVED 只允许读取脱敏数据、restore、delete。
- Runtime、更新、default 和新 Binding 必须拒绝 ARCHIVED/DELETED。
- Model archive/delete 清除 default。
- MCP OAuth legacy disabled 不允许 restore。
- Delete 为 soft delete；DELETED 对普通读取不可见。

### 10.2 Group 状态机

- ACTIVE 可修改 metadata 和成员。
- ARCHIVED 只允许读取、restore、delete。
- 有 active Session association 时禁止 Group archive/delete。
- member 动态变化按 refresh impact 处理。
- Group restore 重新验证项目、成员和跨组 URL 冲突。

### 10.3 锁顺序

1. Credential Group IDs，排序锁定。
2. Default scope lock：`(project_id, protocol)`，使用 advisory lock 或专用 scope row。
3. Credential IDs，排序锁定。
4. Agent/Trigger/Environment/Session consumer aggregate。
5. Sandbox policy rows。

只写“Credential ID 排序”不足以解决并发设置两个 default 时的范围竞争。

### 10.4 Snapshot materialization 原子协议

创建 Session、Task 自动 Session 或 Trigger 执行 Session 时必须在一个 Application transaction 中：

1. 读取 Agent/Agent Version 和 Environment。
2. 通过 `CredentialReferenceCodec` 收集全部 Group/Credential ID。
3. 按统一锁顺序锁定 Group、Credential 和 consumer aggregate。
4. 在锁内重读 Group、Credential、Agent、Environment 和 Version；不得继续使用锁前缓存的 Resource/Group 状态。
5. 比较 consumer version/updated marker，并重新计算 reference 集合。
6. 如引用集合发生变化，释放事务并有界重试。
7. 对锁内重读结果执行 state、project、kind、scheme 和全部 Binding Policy。
8. 构造并持久化 Snapshot、Session association、Audit 和 policy pending。
9. 单次 commit。

Credential archive/delete 在持有同一 Credential lock 时重新扫描已提交依赖，因此不能穿过 Snapshot 创建窗口。

只“先读 active、再获取锁”仍然存在 TOCTOU：archive 可在第一次读取后提交，Snapshot 随后拿到锁但继续使用缓存的 active 对象并创建新 Session。锁的正确性来自锁后重读和重新校验，而不是来自锁调用本身。

---

## 11. Application Transaction 与副作用

```text
Route / Worker
  → Credential Application Service
      → authorize
      → acquire locks
      → validate policies
      → mutate persistence
      → append audit
      → mark durable impacts pending
      → commit once
  → best-effort after-commit nudge
```

- Domain Policy 不 commit、不 flush、不访问 Redis/HTTP。
- Application Service 是唯一事务边界。
- Audit 和 durable pending 与 mutation 同事务。
- after-commit nudge 失败不得把已提交 mutation 返回为失败；记录 metric 后依赖 reconcile loop。
- mutation API 需要幂等键或明确的重复请求语义，避免客户端因连接中断重复创建。

`CredentialImpact` 必须是权威类型，至少包含 usage、source、project、affected sandbox/session 和 disposition。Environment Binding 更新是否影响现有 Snapshot 必须按 Snapshot 冻结语义裁决：冻结配置的 Session 不读取 live Environment；仅 legacy 无 Snapshot 路径可受 live update 影响。

---

## 12. Runtime Store 与错误边界

### 12.1 Store API

```rust
impl CredentialStore {
    async fn get_active(
        &self,
        project_id: &ProjectId,
        credential_id: CredentialId,
    ) -> Result<CredentialRecord, CredentialRuntimeError>;

    async fn list_active_group_members(
        &self,
        project_id: &ProjectId,
        group_ids: &[CredentialGroupId],
    ) -> Result<Vec<McpCredentialRecord>, CredentialRuntimeError>;
}
```

ProjectId 不得为 Optional。缺失 project context 必须 fail closed。MCP 查询必须联表验证 Session、Group、Credential 同项目且 Group active；关联表后续应增加项目复合完整性约束，而不是只依赖写侧检查。

### 12.2 强类型错误

```rust
enum CredentialRuntimeError {
    NotBound,
    NotFound,
    Archived,
    ProjectMismatch,
    KindMismatch,
    FieldMissing,
    UnsupportedScheme,
    CorruptRecord,
    EnvelopeInvalid,
}
```

只有 `NotBound` 可以表示可选 Binding 没有配置。只要持久化 ID 已存在，其他任何失败都必须终止该 Usage，不能静默跳过。

### 12.3 Resolver 职责

- Model Resolver 校验 `kind=model`、Catalog profile、protocol 和字段集合。
- Environment Injection Resolver 显式把 Service Material 注入 sandbox env。
- HTTP Egress Resolver 只把选中字段放入 Egress Route，不进入 sandbox env。
- Webhook Verifier 是 Python inbound adapter，不属于 Rust egress。
- MCP Resolver 按 Group 动态解析 active member，冲突或损坏 fail closed。

模型材料允许在进程内短暂形成构建中间值，但中间类型不得可序列化为 sandbox env。构造 Egress Route 后必须验证真实 key 未进入最终 env、文件、命令行或日志。

---

## 13. Reference Codec 与 Snapshot Version

### 13.1 Environment 目标字段

```json
{
  "environment_credential_ids": ["cred_..."],
  "egress_services": [
    {
      "service_credential_id": "cred_...",
      "inject": {
        "type": "bearer",
        "credential_field": "API_TOKEN"
      }
    }
  ]
}
```

### 13.2 Decoder 版本

| 版本 | 判定 | 可读 key |
|---|---|---|
| legacy-v0 | 无 schema 的历史 Snapshot | `secret_ref`、`secret_refs`、`service_credential_id`、`secret_key` |
| v1 | `joysafeter.agent_execution_snapshot.v1` | v1 key，同样包含已知 legacy alias |
| v2 | `joysafeter.agent_execution_snapshot.v2` | `model_credential_id`、`environment_credential_ids`、`credential_field` |

未知显式 schema fail closed。无 schema 不能直接按未知版本失败，因为现有迁移没有为所有历史 Snapshot 补 schema。

### 13.3 Writer 与 Frontend

新增机器可读工件：

```text
backend/contracts/credential_reference_contract.json
```

它必须包含 snapshot schema、canonical key、legacy alias、consumer surface、错误分类和 test vectors。Python、Rust、Frontend contract test 和 backfill 读取同一工件。

Python Agent/Session writer、Trigger writer、Rust Scheduler writer 必须共享该 contract。Frontend 是非受控缓存客户端，不能被视为可枚举、可同步切换的 writer fleet：用户可能在 E2 后仍打开旧 tab，旧静态资源也可能被浏览器或 CDN 缓存。如果后端直接接受原 JSON 并原样持久化，旧 Frontend 会在 backfill 后重新写入 `secret_refs`/`secret_key`，使“旧 key 计数归零”不稳定。

因此滚动协议必须区分 API 兼容与持久化 contract：

- E1：Backend API request decoder 接受 legacy/new key，立即 canonicalize 为内部模型；response adapter 在兼容窗口按 API capability 输出兼容表示。
- E1：Python、Rust 和 Backend reader 支持 legacy-v0/v1/v2；Frontend 新版本 dual-read/new-write。
- E2：只切换受控服务端 writer。Backend 无论收到旧或新 Frontend payload，都只持久化 canonical new key；Rust/Python Snapshot writer 写 v2。
- E2：Frontend rollout 不参与 rollback floor，也不要求证明“旧 Frontend 实例清零”。
- E3：以持久化旧 key 新增速率为零作为 contract 证据；API legacy request decoder 的移除必须服从独立客户端兼容策略，不能与数据库 backfill 强绑定。

普通业务内部代码不得继续直接读取 legacy key；兼容读取只能存在于版本化 Codec/API boundary。

### 13.4 Live Environment backfill

Backfill 是可恢复管理任务，不是长事务 Alembic JSON rewrite：

- 按稳定游标分页。
- 幂等转换。
- 使用 row version/updated_at CAS，冲突时重读重试。
- 记录 scanned/changed/conflicted/failed 数量和资源 ID。
- 允许暂停、恢复和 dry-run。
- 只改 live Environment，不改 Snapshot。

---

## 14. 发布阶段

### P0.5-0：契约正确性

- 修复 `model`/`llm` 跨语言不一致。
- 定义 `bearer` legacy alias。
- Runtime 强类型错误，消除已绑定引用的静默跳过。
- 所有 Credential Runtime lookup 强制 project scope。
- 增加真实 DB row→Rust Resolver 集成测试。

### P0.5-A：统一语言与边界

- 建立 Domain Types 和 usage-specific Binding。
- Resource 与明文 Material 分离。
- 提取 Credential、Task Identity、Repository Material 独立 Adapter。
- 活跃类型从 Secret/Vault 迁到 Credential/Sensitive Material 语言。

### P0.5-B：Reference Registry

- 建立 surface 分类、operation-specific disposition 和 consumer descriptors。
- 登记 Agent Version、ephemeral consumer 和 legacy key paths。
- 新旧 dependency 结果 shadow 对账。
- 明确差异预算必须为零，连续稳定窗口和 rollback 条件后才切 blocker。

### P0.5-C：事务与生命周期

- Application Service 成为事务边界。
- 实现 Snapshot materialization 锁协议。
- 实现 default scope lock。
- Group/Resource 状态机、Audit、Impact 和 pending 原子化。

### P0.5-D：Runtime Store 收口

- Rust 只通过 `kernel::credentials` 查询和解密 Managed Credential。
- Harness/Sandbox 移除重复 SQL 和解密。
- Repository/Task Identity 进入独立 Material Adapter。
- 删除 legacy OAuth dispatch 分支；不得把它误称为已经存在的网络 refresh。

### P0.5-E1：Decoder-first

- Backend、Python、Rust 全部部署 legacy-v0/v1/v2 dual reader，Backend API canonicalize legacy/new request。
- Frontend 新版本 dual-read/new-write，但不把浏览器实例计入可观测 reader fleet。
- 保持 writer 写 v1/旧 key。
- 观测并确认受控服务端旧 reader 实例清零。

### P0.5-E2：Writer cutover

- feature flag 切换 Python、Rust 和 Backend canonical persistence writer。
- 新 Snapshot 写 v2，新 Environment 写新 key。
- 旧 Frontend payload 经 Backend canonicalize 后也只能落为新 key。
- rollback floor 提升到全部受控服务端组件均能读 v2。

### P0.5-E3：Backfill 与 contract

- 可恢复回填 live Environment。
- 持久化旧 key 计数归零、旧 key 新增速率持续为零。
- 普通业务代码停止写/读旧 key；legacy Decoder 永久保留读取历史 Snapshot。
- 启用最终语言和 Reference Surface 架构守卫。

---

## 15. Preflight、观测与回滚

Preflight 必须输出：

- Credential kind/identity 不合法行。
- distinct `credential_type` 及资源 ID。
- 所有 live Binding 的项目一致性。
- Agent Version、active Session Snapshot 的 v0/v1/v2/unknown 计数。
- Environment 所有 legacy/new key path 计数，包括顶层 `service_credential_id`。
- MCP normalized URL 冲突。
- project_id 为空但持有 Credential Reference 的 Agent/Session。

Rollback floor：

- 数据库最低版本为现有 `20260815_000002`，P0.5 的“可逆”不表示能降回 P0 前 Schema。
- Registry 切换前保留旧 scanner 作为 shadow。
- v2 writer 开启后不得回滚到只读 v1 的 binary。
- Environment backfill 保持结构等价，compatibility codec 可生成旧表示，但 Snapshot 永不原地改写。

---

## 16. 架构与测试门禁

1. Domain Core 不导入 Pydantic、SQLAlchemy、FastAPI、Redis、HTTP Router。
2. Python managed Credential decrypt 只允许 Material Adapter；Webhook 必须调用该 Adapter。
3. Task Identity、Repository Access 使用独立 Adapter。
4. Rust Credential 表 SQL 只允许 `kernel/credentials/store.rs`，测试 fixture 使用 AST/cfg-aware 守卫或独立 fixture 模块。
5. 所有 Reference key 读写必须经过 Codec。
6. 正向 Registry 与 FK/typed-ID、Codec key path、raw SQL、decrypt/reveal callsite 反向普查按 surface 分类完全对账。
7. `SecretRow`、`RuntimeSecretBinding`、`VaultCredentialRow`、`VaultCipher` 等旧业务名在活跃路径计数为零。
8. Python/Rust 共享 kind、auth scheme、snapshot 和 error contract fixture。
9. 并发测试覆盖 Snapshot create vs archive、default A vs B、Group member mutation vs Session create。
10. E2E 证明模型/MCP/HTTP Egress 材料不进入 sandbox 可见 env，除显式 Environment Injection。
11. 兼容测试证明旧 Frontend payload 经 E2 Backend 后只产生 canonical new-key persistence。

---

## 17. 验收标准

P0.5 只有同时满足以下条件才完成：

1. `model` 是 Python、DB、Rust 唯一 Credential kind 值。
2. legacy `bearer` 数据可确定映射，未知 scheme fail closed。
3. Domain Resource 默认不加载明文 Material。
4. 所有 Binding 使用判别式 Policy。
5. Agent Version 激活重新校验；active Session Snapshot 阻止生命周期变更。
6. Snapshot 创建与 archive/delete 无 TOCTOU。
7. MCP member 动态变化是 refresh impact，Group 生命周期是 blocker。
8. Runtime Store 强制非空 project scope。
9. 已配置但无效的引用不再静默跳过。
10. legacy-v0/v1/v2 Decoder 和全部 writer 滚动发布矩阵通过。
11. Backend API canonicalization、Frontend dual-read/new-write 和 live Environment backfill 演练通过；旧 Frontend 不会重新引入 legacy persistence key。
12. Mutation、Audit、durable pending 同事务；nudge 仅 after commit。
13. 活跃 Credential 业务路径不再使用 Secret/Vault 旧语言。
14. P0.5 文档不宣称 AAD/purpose/key-id 安全属性。
15. Backend、Frontend、Rust、migration、并发和 E2E 门禁全绿。

---

## 18. 被拒绝方案

### 18.1 P0.5 前单独全局重命名

拒绝。没有先建立边界时，只会把旧职责换成新单词，继续保留重复 SQL、解密和生命周期分裂。

### 18.2 把所有 Secret 都叫 Credential

拒绝。Task Identity、Repository Token、Deployment Secret 和 Federation token 具有不同 owner、生命周期和威胁模型。

### 18.3 保留 Vault 作为 Credential Group 同义词

拒绝。Group 是授权集合，Vault 通常表达安全存储设施，两者语义不同。

### 18.4 单一万能 Binding Request

拒绝。它无法表达 Catalog、Webhook method、HTTP endpoint/inject 和 MCP Group URL 语义，最终迫使规则重新散落到消费者。

### 18.5 Agent Version 永久阻止 Credential archive

拒绝。历史版本会无限冻结资源。采用激活时重新校验，只有 active Session Snapshot 成为 blocker。

### 18.6 在 P0.5 顺带实现 `enc:v2`

拒绝。领域/事务重构与不可降级的全库密码学迁移需要独立门禁和 rollback floor。

### 18.7 在 P0.5 顺带删除 Federation token 列

拒绝。Identity Federation 是独立边界；删列需要自己的 ORM expand/contract 发布顺序。

---

## 19. 当前代码证据

| 结论 | 证据 |
|---|---|
| Python/DB 使用 `model` | `schemas/joysafeter_credential.py`、`models/joysafeter_credential.py` |
| Rust 错误要求 `llm` | `kernel/llm_catalog.rs::validate_runtime_secret_with_catalog` |
| Domain Service 反向依赖 API/Pydantic | `services/joysafeter_credential_service.py` imports |
| 当前依赖扫描硬编码且遗漏 Agent Version | `CredentialService.dependencies` |
| Python Snapshot writer | `JoySafeterAgentService.build_execution_snapshot` |
| Rust Snapshot writer | `scheduler.rs::build_agent_execution_snapshot` |
| Session 只锁 Group | `JoySafeterSessionService.create_session`、`_validate_credential_groups` |
| Runtime project scope 可空 | `harness_input_builder.rs::resolve_secret_ref_into_input`、`sandbox_resolver.rs::merge_secret_ref_into_env` |
| MCP 查询缺少完整项目联表约束 | Harness/Sandbox MCP group resolver SQL |
| 历史 `bearer` 被原样迁移 | `20260814_000001_unify_credentials.py`、migration tests |
| v1 AES-GCM 无 AAD | `joysafeter_shared/security/credential_cipher.py` |
| Frontend 仍写旧 Environment key | `frontend/types/managed.ts`、`environments-egress-editor.tsx` |
| Repository material 复用历史 cipher | `joysafeter_session_resource_service.py`、Rust Harness/Sandbox resolver |

实施和评审必须重新核对源码，不得把本规格当作替代代码阅读的事实来源。
