# 统一凭据架构（Unified Credential Architecture）设计

- 状态：设计（v3，经两轮架构审计修订为**实现级**，待评审进入 P0 计划）
- 日期：2026-08-11（v3：吸收第二轮审计的 5 阻断项 + 高风险项，含 Session 快照引用面、Group 授权语义、Consumer Resolver 分层、原子刷新、MCP URL 单一规范化）
- 分支：joysafeter-v2（未上线，无历史数据）
- 性质：伞形（umbrella）架构重构 —— 统一并取代此前三条散线（命名/IA、secret-reference-id 迁移、trigger 凭据授权）

---

## 1. 背景与目标

从前端到后端系统化重构凭据/模型/鉴权域，使产品**自洽、完整、用户复杂度低**。把此前三条散线收拢为一个连贯系统。

原则：
- 不发明新抽象——运行时已存在统一抽象，让上层塌缩到它。
- 未上线、无数据 → **一次成型到目标 schema**，不做兼容/双读/回填/cutover（feedback_prelaunch_no_legacy_cruft）；不做"先用旧名 P2 再改名"这类分步（违背一次成型）。
- 分层：**统一存储 ≠ 统一业务解析器 ≠ 统一用户词汇**，三者各自独立。

---

## 2. 诊断（经代码核实）

### 2.1 现状全景

5 个"凭证类"概念：模型接入（`joysafeter_secrets` kind=llm，按名字 `secret_ref`）、服务凭据（同表 kind=generic，按名字 `credential_ref`）、MCP 凭据库+库内凭据（`joysafeter_vaults`/`_vault_credentials` 两级，按 ID `vault_ids` JSONB）、环境 egress 绑定（藏在 `environment.config` JSONB，按名字）、项目访问令牌（`joysafeter_api_keys`，入站鉴权）。所有"在飞"重构在本分支无代码；alembic 仅 2 文件。

### 2.2 核心根因

> 运行时早已把"出站访问型凭据"统一成一条 `EgressCredentialRoute`；数据模型/引用/IA/命名三层没跟上。要让上层反映运行时已有的抽象，而非发明新抽象。

### 2.3 代码证明（4/5 收敛）

唯一类型 `lds_backend.rs:197 EgressCredentialRoute` + `enum EgressKind{Llm,Mcp,Git,External}`（`:168`，注释"Not used by Envoy rendering" `:200`）；唯一注入 `build_virtual_hosts_json`（`:1038`）不按 kind 分支；但被迫用 4 个各异解析器拼回（llm/mcp/external/git，读不同表不同键）。第 5 个 `secret_refs` 是 env-var 注入模式（沙箱可见），API key 是入站——两根另轴。

### 2.4 四处不自洽

引用机制分裂（名字/ID/两者混用，`created_at DESC LIMIT 1` 脆弱）；IA 散落 3 组 + 入站/出站混语义；命名漂移；流程不闭环（trigger 无 vault_ids、`secret_ref` 同名冲突、MCP OAuth 死路径）。

---

## 3. 目标架构

### 3.1 三层模型

| 层 | 是什么 | 持有 |
|---|---|---|
| **Credential Resource** | 项目内、可稳定引用与审计的托管认证材料 | ID / kind / name / 加密材料 / kind 专属元数据 / 生命周期 |
| **Credential Binding** | **谁**用它、目标、用哪个字段、如何消费 | 各消费方持有（标量列 / JSON / 关联表），**不建全局投影表** |
| **Credential Consumer Resolver**（消费适配器） | 运行时把 Binding+Resource 编译成具体消费形态 | 见下三个子适配器 |

第三层是**消费适配器**而非仅"出站路由编译器"——它必须覆盖表中所有消费者：

- **出站 egress**（model/mcp/service）→ `EgressCredentialRoute`（既有，不动）
- **入站 webhook 鉴权**（trigger）→ `WebhookAuthService`（HMAC/Bearer/Token 校验，`trigger_webhook_auth_service.py:60`，**不编译为 egress route**）
- **沙箱环境变量注入**（env-var 模式的 service 凭据）→ 直接注入容器 env

**凭据（Credential）定义**：项目内、可稳定引用和审计的托管认证材料；**目标端点与消费方式由 kind 或消费方 Binding 决定**。

### 3.2 已锁定决策

1. **合表**：secrets + vaults/vault_credentials 条目层 → 一张 `joysafeter_credentials`（kind 判别）。
2. **MCP 分组保留 = 授权集合（非标签）**：vault → `joysafeter_credential_groups`；`kind=mcp` 的凭据 `group_id NOT NULL`（保持现状）。语义见 §3.5b。
3. **复用现有 `CredentialId`**（`ids.py:145` 今天是 vault-credential id）→ 改为统一 credential id，`kind` 为数据字段；退休 `SecretId`/`VaultId`；新增 `CredentialGroupId`。
4. **命名不强并（§3.12）**：后端 kind=model/mcp/service，用户对象名不强迫都叫"凭据"——模型对象 = **模型连接**，其材料 = 模型访问密钥（材料名待确认，见 §7）。
5. **`project_id NOT NULL`**：全局凭据 API 不可达（`secrets.py:358`）→ 收 NOT NULL、删全局唯一索引。
6. **字段一次命名到位**：trigger 入站鉴权字段 P0 直接命名 `webhook_auth_credential_id`/`webhook_auth_field`（不先用旧名 P2 再改）。

### 3.3 `joysafeter_credentials` 表（Credential Resource）

列：`id: CredentialId` PK；`project_id` FK NOT NULL；`kind`∈{model,mcp,service}；`name`；`data: JSONB`（加密材料，契约见 §3.9）；`provider,protocol`（model）；`is_default`（model）；`mcp_server_url` + `normalized_mcp_server_url`（mcp，见下）；`credential_type`（mcp，枚举统一见 §3.14）；`oauth_config: JSONB`（mcp）；`group_id: CredentialGroupId`（mcp，NOT NULL by CHECK）；`archived_at,deleted_at,created_at,updated_at`。

**约束：**
- CHECK `kind_identity`：model 需 provider+protocol、禁 mcp_*；mcp 需 mcp_server_url+group_id、禁 provider/protocol/is_default；service 禁 provider/protocol/mcp_*/group_id、`is_default=false`。
- **kind 不可变**（更新拒绝改 kind）。可变性：model 的 provider/protocol、mcp 的 url/credential_type、group 归属——**均不可变**（改 = 删旧建新），只允许改 name/data/is_default/archived。（简化心智 + 避免 URL/kind 漂移。）
- **名字唯一**：`UNIQUE(project_id, kind, name) WHERE deleted_at IS NULL`。
- **model default 唯一**：`(project_id, protocol) WHERE is_default AND kind='model' AND archived_at IS NULL AND deleted_at IS NULL`（**排除归档/软删**）。归档默认连接时须清除或转移 default（§3.6）。
- **MCP URL 唯一**：`UNIQUE(group_id, normalized_mcp_server_url) WHERE kind='mcp' AND deleted_at IS NULL`。
- **组↔凭据同项目复合 FK**（审计建议，采纳）：`credential_groups UNIQUE(id, project_id)` + `credentials(group_id, project_id) → credential_groups(id, project_id)`，DB 层保证凭据不能落进别项目的组。（这是比 agent↔credential kind-FK 更便宜、更干净的一处，采纳；agent/trigger 侧仍用普通 FK + service 层校验 kind/生命周期。）
- **FK 索引**（Postgres 不自动建）：credentials.project_id、credentials.group_id、credential_groups.project_id、agents.model_credential_id、triggers.webhook_auth_credential_id、所有关联表两侧。

**MCP URL 规范化（审计高风险项，修正 v2 的错误描述）：**
- v2 说"去 query/fragment"是**错的**——现有 `mcp_credential_url_keys`（`harness_input_builder.rs:31`）不去 query/fragment，且生成**多候选键**逐一匹配。
- v3 定义**单一规范化契约**（存储列 `normalized_mcp_server_url`，写时由共享函数生成）：lowercase host、去尾 `/`、默认端口归一——**query/fragment 是否参与身份需 P0 明确并写死**（倾向：保留 query，因 MCP endpoint 可能带路由参数）。
- 运行时匹配**必须收敛到同一规范化函数**（替换多键候选逻辑），并提供 **Python/Rust 共享测试向量**保证两侧一致。

### 3.4 `joysafeter_credential_groups` 表

`id: CredentialGroupId`（前缀 `credgrp_` 待确认）PK；`project_id` FK NOT NULL；`name,description`（`UNIQUE(project_id,name) WHERE deleted_at IS NULL`）；`archived_at,deleted_at,created_at,updated_at`。成员 = `credentials.group_id`（1:N）。

### 3.5 Binding 层 + 完整性四层

引用统一按 ID；完整性**分四层、各由谁保证**（不再宣称"数据库直接保证"）：

| 消费方 | Binding 形态 | 引用完整性 | 项目/kind/生命周期 |
|---|---|---|---|
| Agent 模型连接（live） | 标量列 `model_credential_id` | 原生 FK RESTRICT | service 层 + 写时行锁 |
| **Session 执行快照** | `agent_snapshot` 内 `model_credential_id` + 内嵌 environment.config 的凭据 ID | 无 FK（JSON 内） | **归档/删凭据时须扫描活跃会话快照**（§3.6）；见下 Blocker 1 |
| Trigger 入站鉴权 | 标量列 `webhook_auth_credential_id` + `webhook_auth_field` | 原生 FK RESTRICT | service 层（kind=service） |
| Environment egress / env-var | `config` JSONB 内 `service_credential_id` | 无 FK | service 层写校验 + 删扫描 + 锁（§3.7） |
| Session → 分组 | 关联表 `joysafeter_session_credential_groups` | 原生 FK 两侧 | service 层 |
| Trigger Grant → 分组 | 关联表 `joysafeter_trigger_credential_grant_groups`（**P2A**） | 原生 FK 两侧 | service 层 |

**Blocker 1（审计，已核实 `run_spec.rs:76/81`）——Session 快照是被遗漏的引用面：** 执行时 `secret_ref` 与整个 environment.config **优先读 `session.agent_snapshot`**（快照赢、live 兜底）。所以只改 live 的 `agents.model_credential_id` 和当前环境配置**不够**。P0 必须：
- 快照字段 `secret_ref` → `model_credential_id`；快照内 environment.config 的凭据引用 → ID。
- 凭据/分组的**归档、删除依赖检查纳入活跃会话快照**（否则 Agent 改绑后旧会话仍引用已删/已归档凭据 → 悬空）。
- Rust `run_spec.rs`、Python snapshot builder、相关测试同步改。
- 依赖查询 = `UNION(agent 列, trigger 列, env config 扫描, session 关联表, grant 关联表, **活跃会话快照**)`。

### 3.5b Credential Group 授权语义（审计 Blocker 2）

Group 不是标签，是**可授权的 MCP 凭据集合**——往组里加一条凭据会扩大所有绑定该组的 Session/Trigger 的权限。明确：
- **动态授权集**：运行时按当前组成员解析（保持今天 `resolve_vault_credentials` 每次任务实时读成员的行为）。
- **成员变更（增/移/归档）必须审计 + 刷新在线网络策略**（等同凭据变更，§3.6/§3.10）。
- **多组同 URL 冲突（Blocker 3，已核实 `harness_input_builder.rs:719` HashMap 后写覆盖、无序）**：在 Session/Grant **绑定组时** 及 **组成员变更时** 检测规范化 URL 交集，**冲突即拒绝**，不允许隐式覆盖（关联表无优先级字段，靠拒绝保证确定性）。
- Trigger Grant 是否额外记录**授权时成员快照**（更强的不可扩权保证）留 **P2A** 定；P0 的 Session 采用动态集。

### 3.6 生命周期状态机（审计 High 1，等价保留现有行为）

| 操作 | 被引用凭据 | 被引用分组 |
|---|---|---|
| 更新 | 允许；**同事务刷新在线策略**（§3.9 原子性） | — |
| 归档 | 被活跃引用（含**活跃会话快照**）则拒绝；仅阻止新引用 | 活跃 Session 存在则拒绝 |
| 软删 | 被引用则 service 层拒绝（FK 只挡物删） | 同 |
| 强删 | FK RESTRICT | 同 |
| 分组归档 | — | **不级联**归档成员（P0 决策，已定，非开放项）；成员须先各自处理 |
| 默认模型连接归档 | 归档/删除前须**清除或转移** default（default 唯一索引已排除归档/软删） | — |

FK RESTRICT 只挡物删；`archived_at`/`deleted_at` 由 **service 层** 拒绝/处理。这些行为今天已存在（`secrets.py:467` 刷新、活跃会话阻止归档），重构**等价保留**。

### 3.7 并发与锁（审计 High 2，扩展覆盖面）

TOCTOU：`扫描未引用 → 另事务写引用 → 删凭据 → 悬空`。对策：
- **所有 Binding 的 create/update/archive/delete，以及 Group 绑定/成员变更/归档**，都对相关凭据行加锁（`SELECT ... FOR UPDATE` 或 `pg_advisory_xact_lock(hash(credential_id))`）——不只是 Environment 删除。
- 一致加锁顺序；持锁期间不调网络接口（事务短）；无效 ID fail-closed。

### 3.8 原子变更 + 策略刷新（审计 Blocker 5，已核实非原子）

现状：`update_secret` 提交 → 再调 `refresh_...` 二次提交（`network_policy_refresh.py:72`）。两提交间进程挂 → DB 换新凭据但沙箱未标 pending → Envoy 长留旧凭据（撤销/轮换危险）。

P0 明确事务边界（**一次提交**）：`改凭据/成员 + 写审计事件 + 将项目活跃沙箱标 networking_status=pending`（`refresh_...` 的 mark-pending 逻辑并入同事务，去掉其内部 commit）→ 提交。**提交后**的 Redis nudge 仅作加速（现有 durable reconcile 循环兜底不变）。

### 3.9 `data` JSONB 字段契约（审计 High 5，强化）

- **形态**：扁平 `dict[str, str]`；字段名校验；**上限**（字段数、键长、值大小）防滥用。
- **敏感 vs 明文**：沿用 `_is_display_safe_secret_key` 白名单（默认拒绝，`secret_service.py:110`）；detail 脱敏。
- **掩码更新**：沿用 `merge_update_plaintext`（`:139`）——传入 == 掩码形式则保留原值，绝不把 `********` 存真值。
- **每 kind 字段集**：model 由 catalog credential profile 定义；mcp = token 类；service = 任意 key/value（受上限约束）。OAuth token 存 `oauth_config` 专用键。
- **加密信封**：`enc:v1:` 格式版本 + **Python/Rust 共享加解密测试向量**（两侧 `CredentialCipher`/`VaultCipher` 必须兼容）。**密钥轮换 = YAGNI，本轮不做**（预发布单密钥；日后需要再设计）。

### 3.10 权限 / 脱敏 / 审计（审计 High 6，继承 + 扩展）

读 = reader 看元数据+脱敏值；写/建/删/改/**组成员变更** = `require_joysafeter_write`。detail 脱敏。每次变更（含成员增移）写 `audit_joysafeter_event`，details 只含 name/kind/provider/keys，**不含 value**。OAuth/Grant 授权权限在 P2A/P2B。

### 3.11 两根划出去的轴

env-var 注入 = service 凭据的 Consumer Resolver 一种适配器（Environment Binding 定注入模式）；纯明文 `env_vars` 非凭据留环境配置。项目访问令牌 = 入站鉴权独立轴（词汇"令牌"）。Git repo-token 派生插件留原处。

### 3.12 命名（用户裁决：模型连接）

| 后端 kind | 产品对象名 | 材料名 |
|---|---|---|
| model | **模型连接 / Model Connection** | 模型访问密钥（待确认，见 §7） |
| mcp | **MCP 凭据**（在 **MCP 凭据库/group** 内） | token/oauth |
| service | **服务凭据 / Service Credential** | key/cookie/token |

- 菜单沿用 `模型与凭据`；`环境变量`、`访问令牌` 分列。
- **消歧陷阱**：网络义 `连接`（测试连接/连接失败/已连接）**不得**被扫进对象名 rename；只改实体义。
- trigger 入站鉴权字段命名 `webhook_auth_credential_id`/`webhook_auth_field`（覆盖 HMAC/Bearer/Token，不叫 signing）。
- 收漂移：智能体引擎/Runtime、第三方服务/custom、据/证混写。

### 3.13 错误码（审计五，本轮裁决：采用扁平码表）

按本库 `error_catalog.py` 的扁平注册风格，采用**约 12 个稳定可操作码**（不用两级结构）：`CREDENTIAL_NOT_FOUND` / `CREDENTIAL_KIND_INVALID` / `CREDENTIAL_NAME_EXISTS` / `CREDENTIAL_IN_USE` / `CREDENTIAL_ARCHIVED` / `CREDENTIAL_FIELD_MISSING` / `CREDENTIAL_FIELD_INVALID` / `CREDENTIAL_MASK_CONFLICT` / `CREDENTIAL_PROTOCOL_INCOMPATIBLE` / `CREDENTIAL_GROUP_NOT_FOUND` / `CREDENTIAL_GROUP_URL_CONFLICT` / `CREDENTIAL_ENCRYPTION_CONFIG_MISSING`（OAuth 专属码在 P2B 追加）。

### 3.14 MCP OAuth 现状缺陷（供 P2B 独立安全设计，不在 P0）

已核实：**双重死路径**（`create` 只收 static_bearer + Rust `harness_input_builder.rs:785` 判 `"oauth"` 而 schema 产 `mcp_oauth`）；**无 SSRF 校验**（`:821` 直打 token_url）；**无单飞/行锁**（refresh stampede）。P2B 覆盖：枚举统一、（如需）Auth Code+PKCE+state、Token Endpoint SSRF、client_secret/refresh_token 加密、refresh 单飞/行锁+轮换、失败态与重授权、审计不记 token、刷新后策略重建。

---

## 4. 演进路径（保证每段落地后产品仍可用）

### P0 · 可运行数据骨干（含机械前端）
- 表：`joysafeter_credentials` + `joysafeter_credential_groups` + **`joysafeter_session_credential_groups`**（**仅这三张**；Trigger Grant 关联表属 P2A，P0 不建空表）+ 全约束/索引/复合 FK；折进初始 alembic，squash `20260807_000002`。
- typed id：复用 `CredentialId`（改统一）+ 新 `CredentialGroupId`；退休 `SecretId`/`VaultId`（含 `test_typed_id_architecture.py` 元组）。
- Service：CredentialResource + Group CRUD + `data` 契约 + 权限/审计 + 生命周期（含快照依赖检查）+ 并发锁 + **原子变更+刷新**（§3.8）+ 组成员变更（含 URL 冲突拒绝、审计、刷新）。
- REST：`/credentials`（+kind 过滤、test-connection、set-default、archive、restore）+ `/credential-groups`（+ 成员增/移/list）；删 `/secrets`、`/vaults`。
- 引用切 ID：Agent `model_credential_id`（**含 agent_snapshot**）、Trigger `webhook_auth_credential_id/_field`、Environment JSON（含**快照内 env config**）、Session→关联表。
- Rust：`CredentialStore.get_by_id()` + Consumer Resolver 三适配器（egress 四编译器 / webhook auth / env-var）；`run_spec.rs` 快照字段改 ID；MCP URL 收敛到单一规范化 + 共享测试向量；删按名字解析。
- 前端**机械适配**（调新 API/字段，**保持现有 IA**，不做视觉/词汇重构）。
- 删旧表/路由/字段；全链路测试（后端 + Rust + 前端 mechanical + Python/Rust URL 与 cipher 向量）。
- 取代 secret-reference-id 迁移（标 superseded，不合并）。

### P1 · 纯产品体验重构（不改运行语义）
一个"模型与凭据"入口 + kind 过滤列表 + MCP 凭据库子视图 + 统一创建入口；落地 §3.12 词汇终态（含连接消歧、漂移收敛）。依赖 P0。

### P2 · 授权与 OAuth（拆开）
- **P2A** Trigger Credential Grant（引用 credential group，建 `..._grant_groups` 关联表；是否记成员快照在此定）。
- **P2B** MCP OAuth 安全设计（§3.14，**先出安全 spec 再拆计划**）。
- **P2C** 全流程统一凭据选择器 + 创建闭环。
依赖 P0；P2A/P2B/P2C 相互独立。

**顺序**：P0 → (P1 ∥ P2A ∥ P2C)；P2B 待安全 spec。

---

## 5. 明确不做

全局 Binding 投影表/漂移检测；dual_read/兼容/回填/cutover/观测套件；多语义分支 ID；把纯明文 env_vars 纳入凭据；改 Git repo-token 路径；重构 Envoy/EgressCredentialRoute/事件总线；全局跨项目凭据（`project_id NOT NULL`）；加密密钥轮换（YAGNI）。

---

## 6. 与在飞工作的关系

命名词族 → P1（对象名按 §3.12）；secret-reference-id 迁移 → P0 取代，标 superseded；trigger 授权 → P2A，引用 credential group。

---

## 7. 开放问题（评审/计划时确认）

1. `CredentialGroupId` 前缀（`credgrp_`/其他）。
2. 确认无 seed/admin 脚本创建全局凭据后落 `project_id NOT NULL`。
3. MCP URL 规范化：query/fragment 是否参与身份（倾向保留 query）。
4. **材料名**：`模型访问密钥` vs `模型访问凭据`（审计指其覆盖 API Key + Auth Token；但"凭据"会与保留给 mcp/service 的词重叠）——**你裁**。
5. **Group 授权语义确认**：Session 用动态集（成员变更即影响+审计+刷新）——认可否？Trigger Grant 是否要授权时成员快照（P2A）。

---

## 8. 审计响应记录

**第一轮**（综合 6.7/10）：三层模型、修 3 处过度声明（FK/一查询/P0 半破）、补契约（生命周期/锁/data/权限审计/唯一约束/错误码/OAuth）、用户裁决（模型连接、project_id NOT NULL、关联表正规化）。

**第二轮**（架构 8/10、实现 6.5/10，均已对 HEAD 核实并采纳）：
- Blocker 1 Session 快照引用面（`run_spec.rs:76/81` 核实）→ §3.5 快照纳入引用面 + 依赖检查。
- Blocker 2 Group=授权边界 → §3.5b 授权集语义 + 成员变更审计/刷新。
- Blocker 3 多组同 URL 不确定覆盖（`harness_input_builder.rs:719` 核实）→ 绑定/成员变更时冲突即拒绝。
- Blocker 4 三层模型漏入站 → 第三层改 Consumer Resolver（egress/webhook auth/env-var）；webhook 字段 P0 直接正名。
- Blocker 5 变更/刷新非原子（`network_policy_refresh.py:72` 核实）→ §3.8 同事务一次提交。
- 高风险项：URL 单一规范化契约+共享向量（修 v2 错误描述）、锁协议全覆盖、组↔凭据复合 FK、默认连接生命周期、API 端点枚举、字段可变性、data 上限、cipher 跨语言向量、错误码定为扁平 12 码、P0 只建 3 表、CredentialId 复用非新建、分组归档不级联（消除 §3.6/§7 矛盾）。
- 本轮裁决权/缩范围：材料名与 Group 语义交用户确认（§7）；加密密钥轮换按 YAGNI 不做。
