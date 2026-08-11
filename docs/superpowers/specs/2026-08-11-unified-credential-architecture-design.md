# 统一凭据架构（Unified Credential Architecture）设计

- 状态：设计（方向 + 三项关键决策已确认，待评审后拆计划）
- 日期：2026-08-11
- 分支：joysafeter-v2（未上线，无历史数据）
- 性质：伞形（umbrella）架构重构 —— 统一并取代此前三条散线（命名/IA、secret-reference-id 迁移、trigger 凭据授权）

---

## 1. 背景与目标

用户诉求：从前端到后端，系统化地重构 MCP 凭据库、模型接入、各类凭证鉴权模块，使产品**自洽（一致）、完整（闭环）、用户使用复杂度低**。

当前 `joysafeter-v2` 上凭据域处于"多个半成品叠加、彼此不自洽"的状态：命名词族统一（08-10 中断未提交）、secret-reference-id 迁移（另一分支 ~11/14 任务、从未切换、已判过度设计）、trigger 凭据授权（spec 已提交、未实现）。本设计是把这三条线**收拢成一个连贯系统**，而不是继续单独推进任何一条。

原则（贯穿全文）：
- 不发明新抽象——运行时已存在统一抽象，让上层塌缩到它。
- 未上线、无数据 → 一次成型到目标 schema，**不做任何兼容/双读/回填/cutover**（feedback_prelaunch_no_legacy_cruft）。
- 结构不同的东西不强并（feedback_dont_overengineer）。

---

## 2. 诊断

### 2.1 现状全景（已核实到 file:line）

用户会遇到 5 个"凭证类"概念：

| 概念 | 存储 | 引用方式 | 菜单归属 | 运行时注入 |
|---|---|---|---|---|
| 模型接入（LLM） | `joysafeter_secrets` kind=`llm` | 按名字 `secret_ref` | 资源组·模型与凭据 | Envoy Bearer/x-api-key + 改写 base_url |
| 服务凭据（通用） | `joysafeter_secrets` kind=`generic` | 按名字 `credential_ref` | 同上（同页另 Tab） | Envoy header/cookie/bearer |
| MCP 凭据库 + 库内凭据 | `joysafeter_vaults` / `_vault_credentials`（两级） | 按 ID `vault_ids` | 托管智能体组 | Envoy Bearer + URL 匹配 + OAuth 刷新 |
| 环境 egress 绑定 | 藏在 `environment.config` JSONB | 按名字 `egress_services[].credential_ref` | 托管智能体组·环境 | 复用服务凭据注入 |
| 项目访问令牌（平台 API key） | `joysafeter_api_keys` | key_hash | 管理组 | 不注入（入站鉴权） |

所有"在飞"重构（binding 表 / secret-reference-id / trigger 授权 / dual_read）在本分支**一行代码都没有**；alembic 仅 2 个文件（初始 + secret 列补丁）。

### 2.2 核心根因（一句话）

> **运行时层早已把"出站访问型凭据"统一成同一个抽象——一条 `EgressCredentialRoute`（材料 + 目标端点 + 注入规则，在 Envoy 边界透明注入）——但数据模型、引用机制、信息架构、命名这三层从没跟上，仍把它们当成互不相关的独立功能。**

要做的不是发明新抽象，而是让上三层去反映运行时已存在的抽象。你感到的"不自洽/复杂"，本质是抽象层级的错位，不是某个名字不好——这就是"小修小补"治不好的原因。

### 2.3 代码证明（4/5 收敛）

1. **唯一凭据类型**：`lds_backend.rs:197` `struct EgressCredentialRoute`，带家族标签 `lds_backend.rs:168` `enum EgressKind { Llm, Mcp, Git, External }`；该标签注释明写 `lds_backend.rs:200` *"Credential family. Not used by Envoy rendering."*——注入层根本不区分。
2. **唯一注入路径**：`lds_backend.rs:1038` `build_virtual_hosts_json` 遍历 `&[EgressCredentialRoute]` **不按 kind 分支**，一律 `inject_headers → Envoy request_headers_to_add(OVERWRITE_IF_EXISTS_OR_ADD)`（`:1052-1061`）+ deny-all 兜底。
3. **碎片化被迫在最后一刻拼回**：为喂给这唯一类型，运行时维护 **4 个各异的解析器**，读不同表、用不同键——`extract_llm_egress`（secrets/名字，`sandbox_resolver.rs:1244`）、`build_mcp_egress`（vault_credentials/vault-id，`:1391`）、`build_external_egress`（secrets/名字，`:1596`）、`build_git_egress`（session_repos/session-id，`:1519`）。**输出一致、输入四套 = 碎片化在上层**。

修正（保持严谨）："全部统一"过头。精确是 **4/5 收敛**（LLM/MCP/服务/Git）；第 5 个 `secret_refs` 走 `merge_secret_ref_into_env` 注入为沙箱明文环境变量（沙箱能看见），是不同的**注入模式**，不是不同的概念（见 §3.6）。平台 API key 是入站鉴权，另一根轴。

### 2.4 从根因派生的 4 处不自洽

1. **引用机制分裂（危害最大）**：secret 按名字（且 `created_at DESC LIMIT 1` 取最新，改名断链、同名歧义）、vault 按 ID、environment 两者皆可。前端确认这是"最大复杂度来源"。
2. **信息架构散落**：5 概念散在 3 个菜单组，无"凭据"之家；且把**入站平台鉴权**与**出站智能体凭据**混在同一"密钥/凭据"语义。
3. **命名漂移**：模型概念 3 个名（模型接入 / 智能体引擎 / Runtime），通用密钥 3 个（服务凭据 / 第三方服务 / custom），据/证混写。此为症状。
4. **流程不闭环**：trigger 触发的会话无 `vault_ids`→MCP 凭据永不注入；trigger 的 `secret_ref`（验证入站 webhook 调用方）与 Agent 的 `secret_ref`（模型凭据引用）**同名冲突**；vault 凭据创建只收 static_bearer 但运行时处理 oauth（死路径）。

---

## 3. 目标架构

### 3.1 统一凭据模型（概念）

**一个概念**：凭据 (Credential) = 一份加密材料 + 一个目标端点 + 一条注入规则。三个 kind：

| kind | 目标 | 材料 | 注入（运行时已实现，不动） |
|---|---|---|---|
| **模型凭据** `model` | LLM provider host | api_key | Envoy Bearer/x-api-key + base_url 改写 |
| **MCP 凭据** `mcp` | mcp_server_url | token / oauth | Envoy Bearer + URL 匹配 + OAuth 刷新 |
| **服务凭据** `service` | 任意 HTTP host | key / cookie / token | Envoy header/cookie/bearer **或** 沙箱环境变量 |

### 3.2 已锁定决策（2026-08-11 用户确认）

1. **合表**：`joysafeter_secrets` + `joysafeter_vaults`/`_vault_credentials` 合并为一张 `joysafeter_credentials`（kind 判别）。
2. **MCP 保留分组**：今天的 vault 降级为"可选的凭据分组"——不再是独立两级存储，而是 `model=mcp` 凭据行 + 一个可选分组归属；会话/触发器仍按分组 ID 挂载（保住"容器 vs 条目"语义、最小改动当前挂载模型）。
3. **单一 `CredentialId`**：一个 `CredentialId`（前缀 `cred_`）+ `kind` 数据字段；退休 `SecretId`/`secret_` 与 `VaultId`/`vault_`。不做多语义 ID 拆分。

### 3.3 存储 schema（目标态）

**`joysafeter_credentials`**（合并 secrets + vault_credentials 的条目层）：

| 列 | 说明 |
|---|---|
| `id: CredentialId`（前缀 `cred_`） | PK |
| `project_id` FK nullable | NULL = 全局 |
| `kind: str` ∈ {model, mcp, service} | 家族判别 |
| `name: str` | 展示名 |
| `data: JSONB` | 加密材料（AES-256-GCM，`enc:` 信封），全 kind 通用 |
| `provider, protocol: str?` | 仅 model |
| `is_default: bool` | 仅 model（按 protocol 的默认选择） |
| `mcp_server_url: str?` | 仅 mcp |
| `credential_type: str?` | 仅 mcp（static_bearer / oauth） |
| `oauth_config: JSONB?` | 仅 mcp（client_secret/refresh_token 字段加密） |
| `group_id: CredentialGroupId?` FK nullable | 仅 mcp（可选分组归属） |
| `archived_at, deleted_at, created_at, updated_at` | 生命周期 |

- CHECK `kind_identity`（沿用现有 secrets 的模式并扩展）：model 需 provider+protocol；mcp 需 mcp_server_url；service 禁 provider/protocol/mcp_*、`is_default=false`。
- model 的 default 唯一性沿用现有 partial unique index（按 project/global × protocol）。

**`joysafeter_credential_groups`**（= 今天的 vault，现在只是 mcp 凭据的标签容器）：

| 列 | 说明 |
|---|---|
| `id: CredentialGroupId`（前缀待定，如 `credgrp_`） | PK |
| `project_id` FK nullable | |
| `name, description` | |
| `archived_at, deleted_at, created_at, updated_at` | |

分组成员关系 = `credentials.group_id`（1:N，一个凭据属于至多一个分组，等价于今天 vault_credential.vault_id）。

### 3.4 引用与完整性（统一按 ID）

彻底废弃按名字引用，全部改稳定 ID：

| 消费者 | 现状 | 目标 | 完整性机制 |
|---|---|---|---|
| Agent | `secret_ref: str`（名字） | `model_credential_id: CredentialId?` 标量列 | 原生 FK `ON DELETE RESTRICT` |
| Environment egress | `egress_services[].credential_ref: str`（名字，JSON 内） | `service_credential_id: CredentialId`（JSON 内） | 写时校验 + 删凭据时扫描 config 依赖 |
| Environment env-var | `secret_refs: list[str]`（名字） | `service_credential_id` 列表（见 §3.6） | 同上 |
| Session | `vault_ids`（分组 ID） | `credential_group_ids`（重命名，仍分组 ID） | 运行时解析分组→成员 mcp 凭据 |
| Trigger（webhook 签名） | `secret_ref`/`secret_key`（名字，义冲突） | P0 先切稳定 ID 引用（否则删名字解析后断链）；P2 再把字段**改名消歧**为 `webhook_signing_credential_id`/`webhook_signing_field` | FK `RESTRICT` |

- 标量列（Agent/Trigger）→ 原生 FK，数据库直接保证完整性，**不建 binding 投影表**（那是被判过度设计的部分）。
- JSON 内引用（Environment）→ 无法建原生 FK；写时校验 + 删除时扫描 `config`（未上线小规模，不建派生表）。
- 依赖查询 = `UNION(agent 列, trigger 列, env config 扫描)`，无全局投影表。

### 3.5 运行时（不变 + 唯一变化）

Envoy 边界、`EgressCredentialRoute`、deny-all、透明再注入——**全部不动，它就是终态**。

唯一变化：4 个解析器从"secrets 按名字 + vault 按 ID + env 按名字"统一为"按 ID 读同一张 `joysafeter_credentials`"（`WHERE id=$1 AND project_id=$2`）。mcp 解析器：分组 ID → 成员 mcp 凭据。**这让运行时更简单**（一种查询代替四种），并消灭"按名字取最新"这一整类脆弱解析。

### 3.6 两根划出去的轴

1. **环境变量注入 = 服务凭据的一种"注入模式"，非新概念。** `secret_refs`（注入为沙箱 env 变量）和 `credential_ref`（注入为 egress header）引用**同一个 service 凭据**，只是注入模式不同（env-var / egress-header），由 Environment 的**绑定**决定。纯明文 `env_vars`（如 `LOG_LEVEL`）不是凭据，留在环境配置。
2. **项目访问令牌 (API key) = 入站鉴权，独立轴。** 验证"谁在调用 JoySafeter"，与"智能体出站访问"不同类。独立在账户/项目设置，词汇用**令牌**，与**凭据**彻底分开。（Git repo token 是会话仓库的派生插件，非用户管理凭据，留原处。）

### 3.7 命名词族（统一"凭据"）

落地此前批准、被中断的统一词族：

- 对象级：`模型凭据`（model）/ `MCP 凭据`（mcp）/ `服务凭据`（service）/ 统称 `凭据`。
- 分组：`MCP 凭据库`（credential group，保留"库"以表容器）。
- 菜单：一个 `凭据` 家；`环境变量`、`访问令牌` 分列。
- 消歧：与材料义冲突的 `模型凭据` → 材料侧改叫 `模型访问密钥`（memory 记录的 collision）。
- 命名跟随数据模型（kind 名），不再零散打补丁。

### 3.8 错误码收敛

现 `SECRET_*`/`VAULT_*`/`LLM_SECRET_*`（catalog ~19 + 若干 inline）→ 收敛到 ~5-6：`CREDENTIAL_NOT_FOUND` / `CREDENTIAL_KIND_INVALID` / `CREDENTIAL_NAME_EXISTS` / `CREDENTIAL_IN_USE`（删除被引用）/ `CREDENTIAL_FIELD_INVALID` / `CREDENTIAL_GROUP_NOT_FOUND`。

---

## 4. 演进路径（三段，各自独立可交付）

未上线、无数据 → "演进"不是兼容问题，而是把工作切成自洽、可独立落地的片，每片独立 spec→plan→实现，任一片落地后树不半破。

### P0 · 数据模型骨干（地基）
- 建 `joysafeter_credentials` + `joysafeter_credential_groups`；kind 判别 + CHECK；default 唯一索引。
- 所有引用改 ID + 原生 FK（Agent/Trigger 标量列，**含 trigger webhook 签名引用**）；Environment JSON 内改 ID + 写校验/删扫描；Session `vault_ids`→`credential_group_ids`。
- 单一 `CredentialId` + `CredentialGroupId`；退休 `SecretId`/`VaultId`（含 typed-id 架构测试元组更新）。
- Rust 4 解析器切按-ID 读统一表；mcp 走分组→成员。
- **折进初始 alembic 迁移**，squash `20260807_000002` secret 列补丁；错误码收敛。
- **取代并删除** secret-reference-id 迁移那套（binding 投影表/dual_read/回填/cutover/观测，≈1500 行——本分支本就没有，只需不合并 + 把其 spec/plan 标记 superseded）。
- 依赖：无（根）。价值：直接消灭"引用机制分裂"（最高价值、最低风险的第一刀）。

### P1 · 信息架构 & 命名
- 一个 `凭据` 菜单入口 + 一个列表（按 kind 过滤）+ 一个创建流（按 kind 出动态字段，model 走 catalog）。
- MCP 分组（凭据库）作为凭据下的分组视图，而非独立顶层。
- 落地统一"凭据"词族（§3.7）；把 `环境变量`、`访问令牌` 从"凭据"词汇里分出。
- 依赖：P0 的 kind 模型（对象级命名跟随数据模型）。

### P2 · 流程闭环
- **trigger 凭据授权**（复用 `2026-08-11-trigger-credential-grant-design.md` 的显式/可审计/可撤销/fail-closed 设计，改为引用 credential group）。
- trigger webhook `secret_ref`/`secret_key` → **改名消歧**为 `webhook_signing_credential_id`/`webhook_signing_field`（ID 引用本身在 P0 已切；此处只做语义改名）。
- 补齐 OAuth 创建路径（消除"只能建 static_bearer 但运行时处理 oauth"的死路径）。
- 全流程统一"凭据选择器"组件（按 ID）：agent 创建 / quickstart / 环境 egress / trigger / session。
- 依赖：P0（按 ID 引用）。

**顺序**：P0 → (P1 ∥ P2)。

---

## 5. 明确不做（YAGNI / out of scope）

- 不建 binding 投影表 / 依赖投影层（Agent/Trigger 用原生 FK）。
- 不建 Environment 派生引用表（写校验 + 删扫描足够）。
- 不做 dual_read / 兼容 / 回填 / cutover / migration-run 表 / 观测套件。
- 不做多语义分支 ID（单一 `CredentialId` + kind）。
- 不把纯明文 `env_vars` 纳入凭据；不动 Git repo-token 派生路径。
- 不重构 Envoy / EgressCredentialRoute / 事件总线等运行时既有机制。

---

## 6. 与在飞工作的关系

- **命名词族**（project_joysafeter_credential_domain_naming）→ 并入 P1，随数据模型 kind 名一次落地。
- **secret-reference-id 迁移**（另一分支，过度设计）→ 被 P0 取代；其 spec/plan 标 superseded，代码不合并。
- **trigger 凭据授权**（spec 已提交）→ 并入 P2，grant 改为引用 credential group。

---

## 7. 开放问题（评审时确认）

1. `CredentialGroupId` 前缀取名（`credgrp_` / 其他）。
2. `model` 凭据的 base_url：沿用现状（catalog + `data` 内 base_url_key），还是显式列？倾向沿用现状（P0 不扩面）。
3. Environment `secret_refs`（env-var 模式）与 `egress_services`（header 模式）在 P0 是否统一成"服务凭据绑定 + inject-mode"字段，还是 P0 只切 ID、绑定模型的统一留到 P1/P2？倾向 P0 只切 ID，绑定模型统一放 P1。
