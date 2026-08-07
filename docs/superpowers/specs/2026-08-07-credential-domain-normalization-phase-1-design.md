# 凭证域规范化第一阶段设计

日期：2026-08-07  
状态：已获方向批准，待规格复核  
范围：安全纠错、引用规范化、用户术语统一；不修改数据库表结构和现有公共路径

## 1. 目标

第一阶段把当前分散的“密钥 / 凭证 / API Key / Vault”概念收敛成稳定的用户心智模型，同时修复已经确认的错误引用和生命周期盲点。

本阶段必须达到以下结果：

1. 用户能明确区分平台访问、模型接入、第三方服务认证和 MCP 认证。
2. Webhook Trigger 正确引用一个服务凭据资源，而不是误把凭据字段名当成 Secret 名称。
3. Environment 的直接 Secret 引用和 Egress 凭据引用遵守同一套存在性、类型和生命周期规则。
4. Secret 更新或强制删除后，在线有限网络沙箱重新编译凭据路由。
5. 未完成的 MCP OAuth 创建入口不再产生不可用记录。
6. 现有数据库表、URL、资源 ID、`kind=llm|generic` 和主要 API 字段保持兼容。

## 2. 非目标

本阶段不做以下工作：

- 不合并 `joysafeter_secrets`、`joysafeter_vaults`、`joysafeter_vault_credentials` 或 `joysafeter_api_keys`。
- 不把按名称保存的 `secret_ref` 迁移成 `SecretId`。
- 不实现 MCP OAuth 授权、回调、刷新或 token 交换流程。
- 不迁移或删除现有 `mcp_oauth` 数据。
- 不重命名后端 ORM 类、数据库表、REST 路径或 JSON 字段。
- 不处理 OAuth Account provider token 的存储加密；该问题单独进入安全整改阶段。
- 不移除 Rust 的明文兼容解密路径；该问题单独进入运行时加密契约整改阶段。

## 3. 统一用户术语

### 3.1 中文术语

| 当前概念 | 第一阶段统一名称 | 含义 |
|---|---|---|
| API 密钥 / API Key | 项目访问令牌 | 外部程序调用 JoySafeter API 的项目级身份 |
| LLM Secret / 模型配置 | 模型连接 | 模型供应商、协议、模型、地址和访问凭据的组合 |
| Generic Secret / 通用密钥 | 服务凭据 | Webhook、第三方 HTTP 服务或敏感环境变量使用的加密键值集合 |
| Vault / 凭证库 / 凭据库 | MCP 凭据组 | Session 可选择的一组 MCP Server 凭据 |
| Secret data key | 凭据字段 | 服务凭据或模型连接内部的字段名，例如 `ACCESS_TOKEN` |
| bearer / api_key / cookie | 认证方式 | 平台使用凭据字段生成外部请求认证信息的方法 |

### 3.2 英文术语

| 当前概念 | 第一阶段统一名称 |
|---|---|
| API Keys | Project Access Tokens |
| Model Configuration / LLM Secret | Model Connection |
| Generic Secret | Service Credential |
| Vault | MCP Credential Set |
| Secret Key | Credential Field |

### 3.3 页面信息架构

- `/managed/secrets` 导航与页面标题改为“连接与凭据 / Connections & Credentials”。
- `kind=llm` 在列表、创建弹窗、Agent 和 Quickstart 中展示为“模型连接 / Model Connection”。
- `kind=generic` 展示为“服务凭据 / Service Credential”。
- `/managed/vaults` 展示为“MCP 凭据组 / MCP Credential Sets”。
- `/managed/api-keys` 展示为“项目访问令牌 / Project Access Tokens”。
- 路由、查询参数 `?create=llm|custom` 和内部 i18n key 本阶段允许保留，避免扩大兼容面。

## 4. Webhook Trigger 引用规范化

### 4.1 当前问题

Trigger 的 `secret_ref` 后端语义是 Secret 资源名称，但前端使用 `SecretKeySelect`，该组件返回的是 Secret 内部字段名。这会产生例如 `secret_ref=WEBHOOK_SECRET` 的错误请求，而不是 `secret_ref=github-webhook-prod`。

### 4.2 前端设计

新增面向资源的 `ServiceCredentialSelect`：

- 数据源固定为 `/secrets?kind=generic`，必须处理分页直到 `has_more=false`。
- `value` 和 `onChange` 使用 Secret 的稳定名称，以兼容现有 `secret_ref` 契约。
- 选项展示名称，并可辅助展示可用字段数量。
- 编辑历史 Trigger 时，如果当前名称已不存在，保留一个冲突选项并要求重新选择，不能静默清空。

Trigger Webhook 表单改为两级选择：

1. “服务凭据”：选择 Generic Secret 资源。
2. “凭据字段”：从所选 Secret 的 `keys` 中选择，默认优先 `WEBHOOK_SECRET`。

当 Secret 无字段、字段列表加载失败或历史字段不存在时，表单不可提交并显示可操作错误。

### 4.3 后端设计

Trigger 创建和更新在事务提交前执行：

1. `secret_ref` 必须在当前项目中存在。
2. Secret 必须为 `kind=generic`。
3. `secret_key` 必须存在于解密后的 Secret data 中。

新增或统一错误语义：

- `TRIGGER_SECRET_NOT_FOUND`
- `TRIGGER_SECRET_KIND_INVALID`
- `TRIGGER_SECRET_KEY_NOT_FOUND`

运行时 `WebhookAuthService` 保留相同检查，作为数据漂移和历史脏数据的第二道防线。

## 5. Environment Secret 引用规范化

### 5.1 统一引用集合

Environment 中以下两类引用都属于服务凭据依赖：

- `config.secret_refs[]`
- `config.egress_services[].credential_ref`

后端提供单一引用提取逻辑，返回去重后的 Secret 名称集合。生命周期检查和 API 校验必须复用该逻辑，不再分别解析。

### 5.2 创建与更新校验

Environment 创建和更新必须逐个校验：

1. 引用名称非空。
2. Secret 在当前项目存在。
3. Secret 为 `kind=generic`。

沿用 `ENVIRONMENT_SECRET_NOT_FOUND`，新增 `ENVIRONMENT_SECRET_KIND_INVALID`。错误 data 必须包含 `secret_ref` 和引用来源 `secret_refs` 或 `egress_services`。

### 5.3 沙箱语义保持不变

- `secret_refs` 仍把完整键值集合合并进沙箱环境变量。
- `egress_services[].credential_ref` 仍只在 Envoy 出站边界读取指定字段并注入请求。
- 第一阶段不合并这两种运行时语义，只统一它们的资源类型与生命周期规则。

## 6. Secret 生命周期与在线刷新

### 6.1 引用检查范围

非强制删除 Secret 前检查：

- `Agent.secret_ref`
- `Environment.config.secret_refs[]`
- `Environment.config.egress_services[].credential_ref`
- `Trigger.secret_ref`

发现任一引用即返回资源冲突，错误中包含引用资源类型和名称或 ID。

### 6.2 活跃任务保护

现有活跃任务保护继续阻止修改或删除正在被 Agent 或 Environment 使用的 Secret。Environment 依赖集合扩展后，Egress Service 使用的凭据自然进入同一保护逻辑。

Trigger Secret 只在 Webhook 请求认证阶段读取，不属于任务执行期依赖，因此不加入活跃任务扫描；它只参与普通删除引用保护。

### 6.3 网络策略刷新

以下成功操作后调用 `refresh_live_limited_sandbox_network_policies`：

- Secret 更新。
- Secret 强制删除。
- 普通 Secret 删除成功后执行刷新；正常情况下无引用时不会改变路由，但保持行为一致。

刷新使用：

- `reason="secret.updated"` 或 `reason="secret.deleted"`
- `source_type="secret"`
- `source_id=<SecretId>`

设置协议默认不刷新，因为默认状态不参与运行时自动选择。

## 7. MCP OAuth 暂停策略

### 7.1 前端

- 创建 Credential 弹窗移除 OAuth 切换，固定创建 `static_bearer`。
- 标题和说明明确为“MCP Bearer 凭据”。
- 不展示任何暗示“连接 OAuth”或自动授权的按钮。

### 7.2 后端

- 新建 Vault Credential 时仅允许 `credential_type=static_bearer`。
- 收到 `mcp_oauth`、`oauth` 或未知类型时返回 `VAULT_CREDENTIAL_TYPE_NOT_SUPPORTED`。
- `token_value` 对 `static_bearer` 必须非空。

### 7.3 历史数据兼容

- 已存在的 `mcp_oauth` / `oauth` 记录继续允许读取、列表、归档和删除。
- 不修改历史 `credential_type`。
- 现有记录如果已有可用 `token_value`，运行时仍可按 Bearer token 使用；第一阶段不承诺自动刷新。

## 8. API 与数据兼容边界

保持不变：

- `/api/v1/secrets`
- `/api/v1/vaults`
- `/api/v1/auth/api-keys`
- `Secret.kind = llm | generic`
- `Agent.secret_ref`
- `Trigger.secret_ref` / `Trigger.secret_key`
- `Environment.secret_refs`
- `Environment.egress_services[].credential_ref`
- `Session.vault_ids`

允许新增：

- 更严格的请求校验。
- 新错误码。
- 新前端资源选择组件。
- 用户可见术语与帮助文案。
- Secret 更新和删除后的在线网络策略刷新。

## 9. 权限与信息泄露约束

- Secret 列表只使用 `keys`，不得为了选择字段向无权限用户返回明文。
- Trigger 表单不得请求或缓存真实 Secret value。
- 服务凭据选择器只处理 Secret 名称、ID、字段名和元数据。
- 后端字段存在性校验可以解密，但错误、日志和审计事件不得记录字段值。
- 审计事件只记录 Secret 名称、字段名和引用来源。

## 10. 测试策略

### 10.1 前端

- Trigger 选择器提交 Secret 名称，而不是字段名。
- 选择服务凭据后只显示该 Secret 的字段。
- 历史缺失 Secret 和历史缺失字段阻止提交。
- Vault 创建弹窗只发送 `static_bearer` 和非空 token。
- 中英文关键术语不再出现用户可见的旧名称。

### 10.2 后端

- Trigger 拒绝 LLM Secret。
- Trigger 拒绝不存在的字段。
- Environment Egress 拒绝不存在或非 Generic Secret。
- Secret 删除被 Egress Environment 和 Trigger 引用时返回冲突。
- Secret 更新和删除触发在线网络策略刷新。
- 新建 Vault Credential 拒绝 `mcp_oauth`、`oauth` 和未知类型。
- 历史 OAuth Credential 仍可读取、归档和删除。

### 10.3 回归

- 现有 LLM Secret、Agent 兼容性和 Secret masking 测试保持通过。
- 现有 Vault 加密、项目隔离和归档测试保持通过。
- API Key 鉴权行为不变化。

## 11. 推进顺序

1. 修复 Trigger 服务凭据资源选择和后端校验。
2. 统一 Environment 引用提取与校验。
3. 扩展 Secret 生命周期保护和在线刷新。
4. 暂停 MCP OAuth 创建。
5. 统一中英文术语和帮助文案。
6. 执行相关前后端测试与全量静态检查。

## 12. 验收标准

- 新建 Webhook Trigger 不可能把 `WEBHOOK_SECRET` 之类字段名提交为 `secret_ref`。
- 非 Generic Secret 不可用于 Webhook 或 Environment 服务凭据。
- 被 Environment Egress 或 Trigger 引用的 Secret 无法普通删除。
- Secret 凭据轮换会刷新在线有限网络沙箱的出站凭据。
- 新 UI 不再允许创建伪 `mcp_oauth` Credential。
- 用户界面中四类核心概念使用统一术语。
- 不发生数据库迁移，不改变现有公共路径和主要 JSON 字段。

