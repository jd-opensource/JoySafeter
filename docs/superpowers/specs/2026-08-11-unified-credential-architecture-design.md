# 统一凭据架构（Unified Credential Architecture）设计

- 状态：设计（方向 + 关键决策已确认；经架构审计后修订为**实现级**，待评审进入 P0 计划）
- 日期：2026-08-11（v2 修订：吸收架构审计的 5 阻断项 + 6 高风险项）
- 分支：joysafeter-v2（未上线，无历史数据）
- 性质：伞形（umbrella）架构重构 —— 统一并取代此前三条散线（命名/IA、secret-reference-id 迁移、trigger 凭据授权）

---

## 1. 背景与目标

用户诉求：从前端到后端，系统化地重构 MCP 凭据库、模型接入、各类凭证鉴权模块，使产品**自洽（一致）、完整（闭环）、用户使用复杂度低**。

当前 `joysafeter-v2` 上凭据域处于"多个半成品叠加、彼此不自洽"的状态。本设计把这三条线**收拢成一个连贯系统**，而不是单独推进任何一条。

原则（贯穿全文）：
- 不发明新抽象——运行时已存在统一抽象，让上层塌缩到它。
- 未上线、无数据 → 一次成型到目标 schema，**不做任何兼容/双读/回填/cutover**（feedback_prelaunch_no_legacy_cruft）。
- 结构不同的东西不强并；**统一存储 ≠ 统一业务解析器 ≠ 统一用户词汇**（三者分层，见 §3）。

---

## 2. 诊断（经代码核实，file:line）

### 2.1 现状全景

用户会遇到 5 个"凭证类"概念：

| 概念 | 存储 | 引用方式 | 菜单归属 | 运行时注入 |
|---|---|---|---|---|
| 模型接入（LLM） | `joysafeter_secrets` kind=`llm` | 按名字 `secret_ref` | 资源组·模型与凭据 | Envoy Bearer/x-api-key + 改写 base_url |
| 服务凭据（通用） | `joysafeter_secrets` kind=`generic` | 按名字 `credential_ref` | 同上（同页另 Tab） | Envoy header/cookie/bearer |
| MCP 凭据库 + 库内凭据 | `joysafeter_vaults` / `_vault_credentials`（两级） | 按 ID `vault_ids`（JSONB 列表） | 托管智能体组 | Envoy Bearer + URL 匹配 + OAuth 刷新 |
| 环境 egress 绑定 | 藏在 `environment.config` JSONB | 按名字 `egress_services[].credential_ref` | 托管智能体组·环境 | 复用服务凭据注入 |
| 项目访问令牌（平台 API key） | `joysafeter_api_keys` | key_hash | 管理组 | 不注入（入站鉴权） |

所有"在飞"重构（binding 表 / secret-reference-id / trigger 授权 / dual_read）在本分支**一行代码都没有**；alembic 仅 2 个文件（初始 + secret 列补丁）。

### 2.2 核心根因

> **运行时层早已把"出站访问型凭据"统一成同一个抽象——一条 `EgressCredentialRoute`（材料 + 目标端点 + 注入规则，在 Envoy 边界透明注入）——但数据模型、引用机制、信息架构、命名这三层从没跟上。** 要做的不是发明新抽象，而是让上三层去反映运行时已存在的抽象。

### 2.3 代码证明（4/5 收敛）

1. 唯一凭据类型 `lds_backend.rs:197` `struct EgressCredentialRoute`，家族标签 `lds_backend.rs:168` `enum EgressKind { Llm, Mcp, Git, External }`，注释明写 `:200` "Not used by Envoy rendering"。
2. 唯一注入路径 `lds_backend.rs:1038` `build_virtual_hosts_json` **不按 kind 分支**，一律 `inject_headers → request_headers_to_add(OVERWRITE_IF_EXISTS_OR_ADD)`。
3. 碎片化被迫在最后一刻拼回：4 个各异解析器读不同表/不同键——`extract_llm_egress`（secrets/名字 `:1244`）、`build_mcp_egress`（vault_credentials/vault-id `:1391`）、`build_external_egress`（secrets/名字 `:1596`）、`build_git_egress`（session_repos/session-id `:1519`）。**输出一致、输入四套 = 碎片化在上层。**

修正（严谨）：精确是 4/5 收敛；`secret_refs` 走 `merge_secret_ref_into_env` 注入为沙箱明文 env 变量（沙箱可见），是不同的**注入模式**而非不同概念（§3.11）。平台 API key 是入站鉴权，另一根轴。

### 2.4 四处不自洽

1. **引用机制分裂（危害最大）**：secret 按名字（`created_at DESC LIMIT 1` 取最新，改名断链/同名歧义）、vault 按 ID、environment 两者皆可。
2. **信息架构散落**：5 概念散在 3 个菜单组；入站鉴权与出站凭据混在同一"密钥/凭据"语义。
3. **命名漂移**：模型概念 3 名、通用密钥 3 名、据/证混写（症状）。
4. **流程不闭环**：trigger 触发会话无 `vault_ids`→MCP 凭据永不注入；trigger 的 `secret_ref`（验证入站 webhook）与 Agent 的 `secret_ref`（模型引用）同名冲突；MCP OAuth 是死路径（见 §3.14）。

---

## 3. 目标架构

### 3.1 三层模型（核心框架）

审计的关键修正：把"凭据"从一个平面概念，分成三层，各层职责清晰、不越界。

| 层 | 是什么 | 持有 |
|---|---|---|
| **Credential Resource** | 项目作用域内、可被稳定引用与审计的**托管认证材料** | 身份(ID) / kind / name / 加密材料 / kind 专属元数据 / 生命周期 |
| **Credential Binding** | **谁**用它、目标是什么、用哪个字段、如何注入 | 由各消费方持有（标量列 / JSON / 关联表），**不建全局投影表** |
| **Runtime Route Compiler** | 运行时把 Binding + Resource 编译成代理策略 DTO | `EgressCredentialRoute`（既有，不动） |

**凭据（Credential）的准确定义**（替换旧的"材料+端点+注入"）：

> Credential Resource 是项目作用域内、可被稳定引用和审计的托管认证材料；**目标端点与注入规则由 kind 或消费方 Binding 决定**（model 的端点来自 catalog/data；mcp 的端点在自身 `mcp_server_url`；service 的端点在 Environment Binding）。

这样既不恢复被判过度设计的全局 Binding 表，也不把运行时 DTO 错当领域聚合。

### 3.2 已锁定决策（2026-08-11 用户确认）

1. **合表**：`joysafeter_secrets` + `joysafeter_vaults`/`_vault_credentials` 的**条目层**合并为一张 `joysafeter_credentials`（kind 判别）。
2. **MCP 分组保留**：今天的 vault → 降级为 `joysafeter_credential_groups`（mcp 凭据的标签容器，非独立两级存储）；**`kind=mcp` 的凭据 `group_id NOT NULL`**（保持"凭据必属一容器"的现状，`vault_credential.vault_id` 今天就是 NOT NULL）。
3. **单一 `CredentialId`**（前缀 `cred_`）+ `kind` 数据字段；退休 `SecretId`/`secret_`、`VaultId`/`vault_`。
4. **命名不强并（见 §3.12）**：后端统一 kind=model/mcp/service，但**用户对象名不强迫都叫"凭据"**——模型对象 = **模型连接（Model Connection）**，其材料 = **模型访问密钥（model access key）**。
5. **`project_id NOT NULL`**：已核实全局凭据 API 不可达（`secrets.py:358` 创建一律用 `auth_ctx.project_id`），全局是死复杂度→收成 NOT NULL、删全局唯一索引（`uq_*_global_name`）。日后若要全局凭据再单独设计。

### 3.3 `joysafeter_credentials` 表（Credential Resource）

| 列 | 说明 |
|---|---|
| `id: CredentialId`（前缀 `cred_`） | PK |
| `project_id` FK NOT NULL | §3.2#5 |
| `kind: str` ∈ {model, mcp, service} | 家族判别 |
| `name: str` | 展示名 |
| `data: JSONB` | 加密材料（AES-256-GCM `enc:` 信封）；字段契约见 §3.9 |
| `provider, protocol: str?` | 仅 model |
| `is_default: bool` | 仅 model（按 protocol 默认选择） |
| `mcp_server_url: str?` | 仅 mcp |
| `credential_type: str?` | 仅 mcp（见 §3.14 统一枚举） |
| `oauth_config: JSONB?` | 仅 mcp（client_secret/refresh_token 加密） |
| `group_id: CredentialGroupId?` FK | 仅 mcp，`kind=mcp` 时 NOT NULL（CHECK 保证） |
| `archived_at, deleted_at, created_at, updated_at` | 生命周期 |

**约束：**
- CHECK `kind_identity`（扩展现有 secrets 模式）：model 需 provider+protocol、禁 mcp_*；mcp 需 mcp_server_url+group_id、禁 provider/protocol/is_default；service 禁 provider/protocol/mcp_*/group_id、`is_default=false`。
- **名字唯一**：`UNIQUE(project_id, kind, name) WHERE deleted_at IS NULL`（沿用现有部分唯一索引风格；带 kind 以允许 model/service 同名如 `openai-prod`）。
- **model default 唯一**：沿用现有 `(project_id, protocol) WHERE is_default AND kind='model'` 部分唯一索引。
- **MCP URL 唯一**：`UNIQUE(group_id, normalized_mcp_server_url) WHERE kind='mcp' AND deleted_at IS NULL`。**规范化规则必须与运行时匹配（`harness_input_builder.rs` `mcp_credential_url_keys`）一致**：lowercase host、去尾 `/`、默认端口归一、去 query/fragment——否则创建唯一性与运行时 URL 匹配会打架。
- **FK 索引**（Postgres 不自动建）：`credentials.project_id`、`credentials.group_id`、`credential_groups.project_id`、`agents.model_credential_id`、`triggers.webhook_signing_credential_id`、所有关联表两侧 FK。

### 3.4 `joysafeter_credential_groups` 表

| 列 | 说明 |
|---|---|
| `id: CredentialGroupId`（前缀 `credgrp_`，待评审确认） | PK |
| `project_id` FK NOT NULL | |
| `name, description` | `UNIQUE(project_id, name) WHERE deleted_at IS NULL` |
| `archived_at, deleted_at, created_at, updated_at` | |

成员关系 = `credentials.group_id`（1:N，等价今天 `vault_credential.vault_id`）。

### 3.5 Binding 层 + 完整性四层（审计 Blocker 2）

**引用方式统一按 ID**，但**完整性明确分四层、各由谁保证**——不再宣称"数据库直接保证完整性"：

| 消费方 | Binding 形态 | 引用完整性 | 项目隔离 / kind 兼容 / 生命周期有效 |
|---|---|---|---|
| Agent（模型连接） | 标量列 `model_credential_id: CredentialId?` | 原生 FK `ON DELETE RESTRICT`（仅保证**存在**） | **service 层**校验：同 project、kind=model、未归档/未软删；写引用时行锁凭据 |
| Trigger（webhook 签名） | 标量列（P0 切 ID；P2A 改名 `webhook_signing_credential_id`/`_field`） | 原生 FK `RESTRICT` | service 层：同 project、kind=service、有效 |
| Environment egress | `config` JSONB 内 `service_credential_id` | 无原生 FK（JSON 内） | service 层写校验 + 删凭据时扫描 config；并发见 §3.7 |
| Environment env-var | `config` JSONB 内 ID 列表 | 同上 | 同上 |
| Session → 分组 | **关联表 `joysafeter_session_credential_groups`**（session_id FK, credential_group_id FK, `UNIQUE(session_id, group_id)`） | 原生 FK 两侧 | service 层 |
| Trigger Grant → 分组 | **关联表 `joysafeter_trigger_credential_grant_groups`**（P2A） | 原生 FK 两侧 | service 层 |

**决策（审计 Blocker 5）**：Session/Grant 的多值分组引用**正规化为关联表**（拿到 FK + 索引），取代今天的 `session.vault_ids` JSONB。代价：Rust 读改为 JOIN（可接受）。依赖查询 = `UNION(agent 列, trigger 列, env config 扫描, session 关联表, grant 关联表)`，仍无全局投影表。

**MCP 凭据必属分组（审计 Blocker 4）**：`kind=mcp → group_id NOT NULL`；Session/Grant 只按分组挂载，故无"未分组、不可挂载的孤儿凭据"。

### 3.6 生命周期状态机（审计 High 1，必须等价保留现有行为）

| 操作 | 被引用的凭据 | 被 Session/分组引用的分组 |
|---|---|---|
| 更新 | 允许；**必须刷新在线沙箱网络策略**（等价现 `secrets.py:467` / `vaults.py` 的 `refresh_live_limited_sandbox_network_policies`） | — |
| 归档 | 若被活跃引用则拒绝（等价现"活跃 Session 阻止 Vault 归档"）；仅阻止新引用 | 活跃 Session 存在时拒绝归档 |
| 软删除（deleted_at） | 被引用则拒绝（FK RESTRICT 只挡物删，软删由 **service 层**拒绝） | 被引用则拒绝 |
| 强删除 | FK RESTRICT 挡；仅无引用可删 | 同 |
| 分组归档 | — | 定义：是否级联归档成员 mcp 凭据（P0 决策：不级联，先要求成员先处理） |

**关键**：FK `RESTRICT` 只挡**物理删除**；`archived_at`/`deleted_at` 的软删对 FK 仍有效，必须由 **service 层**显式拒绝/刷新。这些能力今天已存在，重构必须**等价保留**（防回归）。

### 3.7 并发与锁（审计 High 2）

规模小只解决性能、不解决正确性。Environment JSON 引用存在 TOCTOU：`扫描确认未引用 → 另事务写入该 ID → 删凭据 → 悬空引用`。

对策（不需全局 Binding 表）：
- Environment 写引用前、凭据删除前，**都对该凭据行加锁**（`SELECT ... FOR UPDATE` 或 `pg_advisory_xact_lock(hash(credential_id))`）。
- **一致的加锁顺序**；持锁期间**不调网络接口**（事务短）。
- 无效 ID → fail-closed。

### 3.8 运行时（审计 High 3：修正过度声明）

Envoy 边界、`EgressCredentialRoute`、deny-all、透明再注入——**全部不动**。

修正"一种查询代替四种"的过度表述：
- **统一的只是加载层**：三类用户管理凭据统一经 `CredentialStore.get_by_id()` 读取（消灭"按名字取最新"的脆弱解析）。
- **各 kind 的 Route 编译器保留**：`ModelRouteCompiler`（catalog/base_url/header 规则）、`McpRouteCompiler`（分组展开/URL 匹配/OAuth）、`ServiceRouteCompiler`（env binding/字段/allowed_paths）。**Git 保持独立**（来自 `session_repos`，`sandbox_resolver.rs:1519`，不进凭据表）。

即：**统一存储访问 ≠ 统一业务解析器**。

### 3.9 `data` JSONB 字段契约（审计 High 5，必须继承）

统一表不能丢掉现有 secret 的敏感数据契约：
- **每 kind 的字段集**：model 由 catalog credential profile 定义（api_key/auth_token/base_url/model...）；mcp = token 相关；service = 任意 key/value。
- **敏感 vs 可明文**：沿用 `_is_display_safe_secret_key` 白名单（默认拒绝，见 `secret_service.py:110`）——detail 返回时敏感值脱敏。
- **掩码更新语义**：沿用 `merge_update_plaintext`（`secret_service.py:139`）——传入值 == 掩码形式则保留原值，绝不把 `********` 存成真值。
- **加密信封**：`enc:` 前缀；是否加版本号（P0 决策，倾向加 `enc:v1:` 便于未来轮换）。
- OAuth access/refresh token 存 `oauth_config`（专用键），非 `data`。

### 3.10 权限 / 脱敏 / 审计契约（审计 High 6，必须继承）

- **读**：reader 可看元数据 + 脱敏值；**写/建/删/改**：`require_joysafeter_write`（等价现 `secrets.py:455` / `vaults.py:121`）。
- **detail** 返回脱敏字段（不返回真值）；分组成员列表是否需写权限（P0 决策，倾向读权限可见元数据）。
- **审计**：每次变更写 `audit_joysafeter_event`，details 只含非敏感字段（name/kind/provider/keys 列表，**不含 value**，等价现 `secrets.py:474`）。
- OAuth 授权发起、Trigger Grant 授权/撤销的权限在 P2A/P2B 定义。

### 3.11 两根划出去的轴

1. **环境变量注入 = 服务凭据的一种"注入模式"，非新概念。** `secret_refs`（env 变量）与 `credential_ref`（egress header）引用同一 service 凭据，只是注入模式不同，由 Environment Binding 决定。纯明文 `env_vars`（如 `LOG_LEVEL`）不是凭据，留环境配置。
2. **项目访问令牌 (API key) = 入站鉴权，独立轴。** 词汇用**令牌**，与**凭据**彻底分开。（Git repo token 是会话仓库派生插件，非用户管理凭据，留原处。）

### 3.12 命名（用户裁决：模型连接）

后端统一（kind=model/mcp/service），**用户词汇不强并**——用户心智优先于数据库名词对齐：

| 后端 kind | 产品对象名 | 其中敏感材料 |
|---|---|---|
| model | **模型连接 / Model Connection**（provider+protocol+model+base_url+密钥+默认的连接配置，不只是一段材料） | **模型访问密钥 / model access key** |
| mcp | **MCP 凭据**（在 **MCP 凭据库 / group** 内） | token / oauth |
| service | **服务凭据 / Service Credential** | key/cookie/token |

- 菜单：用 `模型与凭据`（现有 `nav.secrets` 标签，正好合用）分组模型连接 + MCP 凭据 + 服务凭据；`环境变量`、`访问令牌` 分列。
- **消歧陷阱（执行时必守）**：`连接` 是同义词——网络义 `连接`（`测试连接`/`连接失败`/`已连接`）**不得**被扫进对象名 rename；只改实体义。与材料义冲突的旧 `模型凭据` 字符串 → 材料侧 `模型访问密钥`。
- 收掉现有漂移：模型概念的 `智能体引擎`(kindLlm)/`Runtime`，通用的 `第三方服务`/`custom`，据/证混写。

### 3.13 错误码（审计五：保住语义）

不做"5-6 个"的过度收敛。目标 = **统一词族+数据结构，不丢故障语义**：保留 ~10-15 个稳定可操作码，或两级结构 `{ "code": "CREDENTIAL_INVALID", "reason": "PROTOCOL_INCOMPATIBLE" }`。至少区分：not_found / kind_invalid / name_exists / in_use（活跃依赖）/ archived / field_missing / field_invalid / mask_conflict / protocol_incompatible / oauth_* / policy_refresh_failed / encryption_config_missing。

### 3.14 MCP OAuth 现状缺陷（供 P2B 安全设计）

已核实的死路径 + 不一致（P2B 必须处理，**不在本 P0**）：
- **双重死路径**：`VaultService.create_credential` 只收 `static_bearer`（其他拒绝）→ oauth 凭据根本创建不了；且 Rust `harness_input_builder.rs:785` 判 `credential_type != "oauth"`，而 schema 枚举是 `mcp_oauth`（无 `"oauth"`）→ 即便有行也永不刷新。**枚举必须统一为单一值。**
- **无 SSRF 校验**：`harness_input_builder.rs:821` 直接 `client.post(token_url)` 打任意存储 URL。
- **无单飞/行锁**：并发任务可同时刷新同一凭据（refresh stampede）。
- 正式 P2B 需覆盖：枚举统一、（如需交互授权）Authorization Code+PKCE+state、Token Endpoint SSRF 防护、client_secret/refresh_token 加密、refresh 单飞/行锁 + 轮换、失败态与重新授权、审计不记 token、刷新后在线 Envoy 策略重建时机。

---

## 4. 演进路径（审计 Blocker 3：重划，保证每段落地后树不半破）

### P0 · 可运行的数据骨干（一次含机械前端，落地后**产品仍可用**）
- 新表 `joysafeter_credentials` + `joysafeter_credential_groups` + 两张关联表 + 所有约束/索引；折进初始 alembic，squash `20260807_000002`。
- 新 typed id `CredentialId`/`CredentialGroupId`；退休 `SecretId`/`VaultId`（含 `test_typed_id_architecture.py` 元组更新）。
- ORM/Service：CredentialResource CRUD + Group CRUD + `data` 契约(§3.9) + 权限/审计(§3.10) + 生命周期(§3.6) + 并发锁(§3.7)。
- REST：`/credentials`（+kind 过滤）+ `/credential-groups`；删除 `/secrets`、`/vaults`。
- 消费方引用切 ID：Agent `model_credential_id`、Trigger webhook（切 ID，改名留 P2A）、Environment JSON、Session→关联表。
- Rust：`CredentialStore.get_by_id()` + 四 Route 编译器适配（含分组展开）；删按名字解析。
- **前端机械适配**：调用改到新 API/字段，**保持现有 IA 与页面结构不变**（不做视觉/词汇重构）。
- 在线策略刷新等价保留；错误码(§3.13)。
- 删旧表/旧路由/旧字段；全链路测试（后端 + Rust + 前端 mechanical）。
- **取代** secret-reference-id 迁移那套（其 spec/plan 标 superseded，代码不合并）。
- 依赖：无（根）。

### P1 · 纯产品体验重构（不改运行语义）
- 一个"模型与凭据"入口 + 一个列表（按 kind 过滤）+ MCP 凭据库子视图 + 统一创建入口。
- 落地 §3.12 用户词汇终态（含 `连接` 同义词消歧、漂移收敛）。
- 依赖：P0。

### P2 · 授权与 OAuth（安全敏感，拆开）
- **P2A** Trigger Credential Grant（复用 `2026-08-11-trigger-credential-grant-design.md`，改为引用 credential group 关联表）+ trigger webhook 字段改名消歧。
- **P2B** MCP OAuth 授权（§3.14 的独立安全设计——**先出安全 spec 再拆计划**）。
- **P2C** 全流程统一凭据选择器 + 创建闭环。
- 依赖：P0（按 ID）；P2A/P2B/P2C 相互独立。

**顺序**：P0 → (P1 ∥ P2A ∥ P2C)；P2B 待其安全 spec 完成。

---

## 5. 明确不做（YAGNI / out of scope）

- 不建全局 Binding 投影表 / 投影相等性校验 / 漂移检测（标量列用 FK，多值用关联表，env 用写校验+删扫描+锁）。
- 不做 dual_read / 兼容 / 回填 / cutover / migration-run 表 / 观测套件。
- 不做多语义分支 ID（单一 `CredentialId` + kind）。
- 不把纯明文 `env_vars` 纳入凭据；不动 Git repo-token 派生路径。
- 不重构 Envoy / `EgressCredentialRoute` / 事件总线。
- 不做全局（跨项目）凭据（`project_id NOT NULL`）。

---

## 6. 与在飞工作的关系

- 命名词族（project_joysafeter_credential_domain_naming）→ 并入 P1；对象名按 §3.12 用户裁决（模型连接，非统一"凭据"）。
- secret-reference-id 迁移（另一分支，过度设计）→ 被 P0 取代，标 superseded。
- trigger 凭据授权（spec 已提交）→ 并入 P2A，改引用 credential group。

---

## 7. 开放问题（评审/计划时确认）

1. `CredentialGroupId` 前缀（`credgrp_` / 其他）。
2. 确认无 seed/admin 脚本创建全局凭据后，再落 `project_id NOT NULL`（已核实 REST 不可达）。
3. `model` 的 base_url：沿用现状（catalog + `data`），不扩面。
4. 分组归档是否级联成员（倾向不级联）；加密信封是否加 `v1` 版本前缀（倾向加）。

---

## 8. 审计响应记录

本文档 v2 吸收了一次架构审计（综合 6.7/10，"方向批准、当前版本尚非实现级"）。所有代码级论断已逐条对着 HEAD 核实：

- **已核实为真并采纳**：Blocker 4（`vault_id NOT NULL`→group NOT NULL，`joysafeter_vault.py:69`）、High 1（在线策略刷新 `secrets.py:467`）、High 5（掩码契约 `secret_service.py:110/139`）、High 6（写权限+审计 `secrets.py:455/474`）、High 4（OAuth 双重死路径 + 枚举 `mcp_oauth` vs `"oauth"` 不一致 `harness_input_builder.rs:785`）。
- **修正的过度声明**：FK "直接保证完整性"（→ §3.5 四层）、"一种查询代替四解析器"（→ §3.8）、"P0 树不半破"（→ P0 含机械前端）。
- **补齐的实现契约**：生命周期状态机(§3.6)、并发锁(§3.7)、data 契约(§3.9)、权限/审计(§3.10)、名字/URL 唯一+FK 索引(§3.3)、错误码语义(§3.13)、OAuth 安全(§3.14→P2B)。
- **用户裁决**：模型对象名 = 模型连接（非统一"凭据"，§3.12）；`project_id NOT NULL`（全局 API 不可达）；Session/Grant 多值引用正规化为关联表（§3.5）。
