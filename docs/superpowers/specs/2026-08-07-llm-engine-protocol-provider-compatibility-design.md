# LLM 引擎、协议、Provider 与密钥兼容性设计

## 状态

- 日期：2026-08-07
- 状态：设计已确认并完成跨层一致性审计
- 系统阶段：全新系统，直接建立最终领域模型
- 范围：LLM Catalog、模型密钥管理、Agent 创建/编辑、Quickstart、后端校验、运行时凭据路由

## 结论

系统统一采用以下关系：

```text
Engine --supports--> Protocol <--implements-- Provider
                                    |
                                    +--configured-by--> Secret

Agent --runs-with--> Engine
Agent --references--> Secret
```

- **Engine** 是 Agent 运行引擎，例如 Claude Code、Codex、Native、Pi。
- **Protocol** 是模型 API 契约，例如 Anthropic Messages、OpenAI Responses、Chat Completions。
- **Provider** 是模型服务商，例如 Anthropic、OpenAI、DeepSeek 或自定义兼容服务。
- **Secret** 是某个 Provider 在某个 Protocol 下的连接配置。
- **Agent** 保存 `engine_kind + secret_ref`，但 Secret 不保存 `engine_kind`。
- Engine 与 Provider 不直接绑定，二者只通过共同支持的 Protocol 产生兼容关系。
- Engine ID 与 Provider ID 命名空间不得重叠；保留名从 Catalog 的 Engine 集合派生，不在业务代码维护副本。

这意味着：引擎在开发时已经确定支持哪些协议；用户选择引擎后，界面只展示该引擎可用的模型配置；同一 Secret 可以被所有支持其 Protocol 的 Engine 复用。

## 目标

1. 彻底分离 Engine、Protocol、Provider、Secret 四个概念。
2. 建立唯一、版本化、可测试的 LLM 能力目录。
3. 让 Agent 创建、编辑和 Quickstart 只获取当前 Engine 可用的 Secret。
4. 让 Secret 创建流程按 Engine、Provider、Protocol 联动，减少无效选择。
5. 让后端和运行时成为兼容性权威，前端只负责友好展示和即时反馈。
6. 让普通用户不需要理解环境变量键名，也能完成模型配置。
7. 让错误在配置阶段被明确发现，而不是进入沙箱后表现为模糊的上游错误。

## 非目标

- 不允许用户自行声明 Engine 支持尚未实现的 Protocol。
- 不建设管理员可任意修改的动态引擎适配器系统。
- 不同步完整在线模型市场；Catalog 只提供经过验证的模型建议。
- 不把 Secret 绑定到单个 Agent 或单个 Engine。
- 不从 Secret 键名、Base URL 或 Provider 别名猜测 Protocol。
- 不接受 `claude`、`codex`、`native`、`pi` 作为 Secret Provider。

## 核心原则

### 1. 引擎能力由代码确定

Engine 支持哪些 Protocol 是适配器实现能力，必须由代码、测试和发布流程确定。Catalog 只能声明真实实现，不能扩大能力。

### 2. Provider 通过 Protocol 与 Engine 兼容

```text
compatible(engine, provider, protocol) =
  protocol in engine.supported_protocol_ids
  and protocol in provider.protocol_bindings
```

### 3. Secret 不保存 Engine

Secret 只保存 `kind + provider + protocol + data`。创建 Secret 时传入的 Engine 仅用于筛选界面和查询，不进入 Secret 持久化模型。

### 4. 所有身份都必须显式提供

- LLM Secret 必须显式提供合法的 Provider 和 Protocol。
- Generic Secret 的 Provider 和 Protocol 必须为空。
- 请求不根据字段内容推断 `kind`、Provider 或 Protocol。
- 非法组合立即返回稳定错误码。

### 5. 后端是权威，运行时再次闭环

前端通过 Catalog 和服务端过滤结果展示选项；Agent 创建、更新和运行前都必须重新校验。运行时在解密和注入 Secret 数据之前完成元数据校验。

### 6. 普通流程隐藏不兼容项

用户已选择 Engine 时，只展示可用 Provider、Protocol 和 Secret。已有配置冲突时不静默替换，而是保留冲突值、解释原因并要求用户处理。

## 初始能力目录

### Protocol

首批 Protocol 使用稳定标识：

| ID | 展示名称 | 说明 |
|---|---|---|
| `anthropic_messages` | Anthropic Messages API | Anthropic Messages 请求与流式响应契约 |
| `openai_responses` | OpenAI Responses API | OpenAI Responses 请求与事件流契约 |
| `chat_completions` | Chat Completions API | OpenAI 兼容 Chat Completions 契约 |

Protocol ID 是 API、数据库和运行时契约。新增不兼容协议时必须新增 Protocol，不能为了复用界面将其错误归入现有协议。

### Engine

首批 Engine 能力矩阵：

| Engine | 支持 Protocol | 推荐顺序 |
|---|---|---|
| `claude` | `anthropic_messages` | Anthropic Messages |
| `codex` | `openai_responses` | OpenAI Responses |
| `native` | 全部三个 | Anthropic Messages、Responses、Chat Completions |
| `pi` | 全部三个 | Chat Completions、Anthropic Messages、Responses |

任何能力增减都必须同时更新 Catalog、Python 合约测试和 Rust 运行时合约测试。

### Provider

首批 Provider 绑定：

| Provider | 支持 Protocol | 凭据模板 |
|---|---|---|
| `anthropic` | `anthropic_messages` | `anthropic_standard` |
| `openai` | `openai_responses`、`chat_completions` | `openai_bearer` |
| `deepseek` | `chat_completions` | `openai_bearer` |
| `custom` | 全部三个 | 按所选 Protocol 使用对应模板 |

`custom` 表示用户明确选择协议的兼容端点，不代表未知 Provider，也不是默认兜底值。

## Canonical LLM Catalog

后端维护版本化 `llm_catalog.yaml`，作为以下信息的唯一来源：

```text
LlmCatalog
  version
  engines[]
  protocols[]
  providers[]
  credential_profiles[]
```

### EngineCapability

```text
id
display_name
enabled
supported_protocol_ids[]
preferred_protocol_ids[]
```

- `supported_protocol_ids` 表示真实能力。
- `preferred_protocol_ids` 只影响排序和推荐，不扩大能力。

### ProtocolDefinition

```text
id
display_name
description
```

### ProviderDefinition

```text
id
display_name
enabled
protocol_bindings[]
```

每个 `ProviderProtocolBinding` 包含：

```text
protocol_id
credential_profile_id
default_base_url
model_suggestions[]
```

### CredentialProfile

```text
id
fields[]
required_any_of[][]
base_url_key
model_key
```

每个字段包含：

```text
key
label
type             # secret | text | url | select
required
placeholder
help_text
options[]
advanced
```

- `required_any_of` 表达“至少填写一组中的一个字段”，例如 Anthropic API Key 与 Auth Token 二选一。
- `base_url_key` 指定连接测试和运行时读取 Base URL 的键。
- `model_key` 指定默认模型字段。
- Catalog 只包含字段元数据，不包含任何项目 Secret 值。

### Catalog 启动校验

服务启动时必须拒绝：

- 重复 ID。
- Engine 引用不存在的 Protocol。
- Provider binding 引用不存在的 Protocol 或 Credential Profile。
- `preferred_protocol_ids` 不是 `supported_protocol_ids` 的子集。
- Credential Profile 的 `base_url_key`、`model_key` 或 `required_any_of` 引用不存在字段。
- Provider 存在重复 Protocol binding。
- 启用的 Engine、Provider 或 Protocol 没有运行时实现覆盖。

## 初始数据库基线

本系统直接修改预发布初始 schema `20260803_000001_initial_schema.py`，保持单一 Alembic head `20260803_000001`。

### Secret 表

```text
joysafeter_secrets
  id
  project_id
  name
  kind             NOT NULL  # llm | generic
  provider         NULLABLE
  protocol         NULLABLE
  data             NOT NULL
  is_default       NOT NULL
  deleted_at
  created_at
  updated_at
```

数据库与应用层共同保证：

```text
kind = llm     => provider IS NOT NULL AND protocol IS NOT NULL
kind = generic => provider IS NULL AND protocol IS NULL AND is_default = false
```

- `kind` 无默认值，创建请求必须显式提供。
- `provider` 和 `protocol` 无 `custom` 默认值。
- LLM Secret 的 Provider/Protocol 必须存在于 Catalog 且形成合法 binding。
- Generic Secret 不参与模型兼容查询和默认值逻辑。
- `claude/codex/native/pi` 作为 Provider 时立即拒绝。
- `kind/provider/protocol` 是 Secret 的连接身份，创建后不可原地修改；切换身份时创建新 Secret，再显式调整 Agent 引用。

### Protocol 级默认值

默认模型配置按项目和 Protocol 隔离：

```text
unique(project_id, protocol)
where kind = 'llm'
  and is_default = true
  and deleted_at is null
```

全局 Secret 与项目 Secret 分别使用部分唯一索引。设置一个默认值时，只取消同一作用域、同一 Protocol 下的旧默认值。

## API 设计

### Catalog

```http
GET /api/v1/llm/catalog
```

返回：

```json
{
  "version": "2026-08-07.1",
  "engines": [],
  "protocols": [],
  "providers": [],
  "credential_profiles": []
}
```

- 需要读权限。
- 返回 `ETag` 和短时私有缓存头。
- 不返回 Secret 值或项目级信息。

### Secret 查询

```http
GET /api/v1/secrets?kind=llm&compatible_engine=codex
GET /api/v1/secrets?kind=llm&provider=openai&protocol=openai_responses
```

- `compatible_engine` 必须由服务端在分页前过滤。
- 未知 Engine、Provider 或 Protocol 返回结构化错误，不返回空列表伪装成功。
- Secret 列表项返回 `kind`、Provider、Protocol、模型摘要、默认标记和 `compatible_engine_ids`，不返回明文凭据。

### Secret 创建与测试

LLM 与 Generic 使用显式 `kind`：

```json
{
  "kind": "llm",
  "name": "openai-production",
  "provider": "openai",
  "protocol": "openai_responses",
  "data": {
    "OPENAI_API_KEY": "...",
    "OPENAI_MODEL": "gpt-5"
  },
  "is_default": true
}
```

```json
{
  "kind": "generic",
  "name": "github-token",
  "data": {
    "GITHUB_TOKEN": "..."
  }
}
```

连接测试请求同样必须显式提供 `kind=llm + provider + protocol + data`。后端根据 Provider binding 的 Credential Profile 读取字段，不通过键名选择适配器。

Secret 更新接口只更新凭据数据和允许的展示属性，不接受 `kind/provider/protocol`。这样更新 API Key、Base URL 或模型不会改变兼容关系；切换服务商或协议必须创建新 Secret。

### Agent 创建和更新

Agent 提交：

```json
{
  "engine_kind": "codex",
  "secret_ref": "openai-production"
}
```

后端加载 Secret 元数据并校验：

1. Secret 存在且在当前项目作用域可见。
2. `kind == llm`。
3. Provider/Protocol binding 合法。
4. Engine 支持该 Protocol。

任何失败都拒绝保存 Agent。

Agent 兼容校验只读取 Secret 元数据，不解密 `data`。Credential Profile 完整性在 Secret 创建、更新和连接测试时校验。

## 后端兼容服务

Python 领域层提供纯函数和结构化错误：

```text
compatible_protocol_ids(engine_id, provider_id?)
compatible_provider_protocol_pairs(engine_id)
compatible_engine_ids(provider_id, protocol_id)
validate_provider_protocol(provider_id, protocol_id)
validate_engine_protocol(engine_id, protocol_id)
validate_llm_secret(engine_id?, provider_id, protocol_id, data)
```

`compatible_provider_protocol_pairs` 返回按 Catalog 顺序排列的 `(provider_id, protocol_id)`，供服务端过滤和前端辅助排序使用。

稳定错误码至少包括：

- `LLM_ENGINE_UNKNOWN`
- `LLM_PROVIDER_UNKNOWN`
- `LLM_PROTOCOL_UNKNOWN`
- `LLM_PROVIDER_PROTOCOL_UNSUPPORTED`
- `LLM_PROTOCOL_NOT_SUPPORTED_BY_ENGINE`
- `LLM_SECRET_KIND_REQUIRED`
- `LLM_SECRET_PROVIDER_REQUIRED`
- `LLM_SECRET_PROTOCOL_REQUIRED`
- `LLM_SECRET_PROVIDER_RESERVED`
- `LLM_SECRET_CREDENTIALS_INCOMPLETE`
- `AGENT_SECRET_INCOMPATIBLE`

错误数据只包含 Engine、Provider、Protocol、Secret ID/名称等元数据，不包含 Secret 值。

## 运行时闭环

Rust 运行时读取同一份 Catalog，并在解密前执行：

```text
validate_runtime_secret(engine_kind, kind, provider, protocol)
```

处理顺序：

1. 查询 Secret 的 `kind/provider/protocol/data`。
2. 校验 `kind == llm`。
3. 校验 Provider/Protocol binding。
4. 校验 Engine/Protocol compatibility。
5. 根据 Credential Profile 路由凭据。
6. 通过后才解密并注入环境变量、Base URL、模型和 egress 信息。

这不是前端或 API 校验的替代，而是数据面最后一道一致性保护。

## 前端交互设计

### 统一组件

#### `LlmSecretConfigurator`

负责：

- 可选 Engine 上下文。
- Provider、Protocol 联动。
- Catalog 驱动的动态凭据字段。
- 连接测试、创建、错误恢复。
- 创建成功回调。

组件持有：

```text
engineId
providerId
protocolId
values: Record<string, string>
connectionTestFingerprint
connectionTestState
```

`values` 是 Credential Profile 字段的唯一表单状态。Provider 或 Protocol 改变时，只保留新 Profile 中仍存在且语义相同的字段，其余字段立即从状态中移除。

`stableConnectionFingerprint({ providerId, protocolId, values })` 对字段键排序后生成仅存在于内存中的稳定字符串，用于判断已通过的连接测试是否因输入变化而失效。它不得写入日志、Local Storage、遥测或错误信息。

#### `CompatibleSecretPicker`

负责：

- 根据 Engine 请求服务端过滤后的 Secret。
- 展示 Provider、Protocol、模型和默认标记。
- 区分加载、失败、空列表和正常状态。
- 提供“创建模型配置”入口。

### Secret 页面

创建入口先选择：

- 模型配置（默认推荐）。
- 通用密钥。

模型配置流程：

1. 可选“计划用于哪个引擎”，并明确说明“仅用于筛选，不会绑定”。
2. 只展示至少有一个可用 Protocol 的 Provider。
3. Provider 与 Engine 交集只有一个 Protocol 时自动选择并隐藏 Protocol 控件。
4. 有多个 Protocol 时显示带简短解释的选择控件。
5. 普通字段使用业务名称；原始环境变量键只在“高级设置”中展示。
6. 连接测试和创建均在当前表单完成。

### Agent 创建

交互顺序：

1. 选择 Engine。
2. 加载 `compatible_engine=<engine>` 的 Secret。
3. 仅展示兼容 Secret。
4. 没有可用 Secret 时，在同一 Dialog 内切换到模型配置子视图。
5. 创建成功后返回 Agent 表单并选中新 Secret，之前填写的 Agent 内容保持不变。

初始自动选择规则：

- 只有一个兼容 Secret 时可自动选择。
- 兼容列表中只有一个默认 Secret 时可自动选择。
- 其他情况不自动选择。

`is_default` 只用于同一 Protocol 内的推荐与初始选择，不代表运行时会在
`secret_ref` 为空时自动解析默认 Secret。Agent 不绑定模型配置时，运行时不会从
Secret 模块注入模型凭据；界面必须明确表达这一点，不能暗示存在隐式回退。

切换 Engine 时：

- 当前 Secret 仍兼容：保留。
- 当前 Secret 不兼容：创建流程清空并显示说明。
- 不自动选择另一个生产 Secret替代它。

### Agent 编辑

编辑页面不得把冲突值悄悄变成空值：

- 保留当前 Secret 名称和元数据。
- 显示“当前模型配置不支持所选引擎”。
- 提供“重新选择模型配置”和“恢复原引擎”。
- 冲突解决前禁用保存。

### Quickstart

Quickstart 使用与 Agent 创建完全相同的 Catalog、兼容 Secret 查询、选择策略和 `LlmSecretConfigurator`。没有可用 Secret 时留在当前步骤创建，不跳转到 Secret 页面。

### 状态与可访问性

- Catalog 和 Secret 查询期间显示骨架或加载提示，不短暂显示“无可用配置”。
- 请求失败保留合法输入，并提供就地重试。
- 连接测试失败不清空凭据。
- 输入变化后将连接测试结果标记为过期。
- Dialog 内使用单层焦点陷阱，不打开嵌套 Dialog。
- 所有选择器、错误提示和返回操作支持键盘。
- 小屏幕改为单列布局，主要操作始终可见。

## 缓存与一致性

- Catalog 在后端启动时加载为不可变快照。
- Catalog API 通过版本和 `ETag` 缓存。
- 前端 Catalog Query 使用稳定键；版本变化时使派生查询失效。
- Secret 的 `compatible_engine_ids` 在响应时计算，不持久化。
- Catalog 变化不会自动修改 Agent；Agent 下一次编辑或运行时重新校验。

## 一致性审计补充约束

- `enabled=false` 在 Python 兼容服务、Agent/Quickstart API、Rust 运行时和前端选项中统一表示“不可新建、不可选择、不可运行”。
- Rust 必须严格解析同一份 YAML，校验重复 ID、交叉引用、Credential Profile 字段引用和未知字段，不能依赖 Serde 静默忽略。
- Catalog 中删除或禁用 Provider/Protocol 后，已有 Secret 仍可在列表和冲突提示中显示，但兼容引擎为空、详情只读、Agent 保存和运行被阻止。
- Catalog `version` 必须进入所有包含 Catalog 派生字段的 Secret Query Key，包括通用列表、详情、Engine 兼容查询、按名称冲突查询和按 Protocol 查询；稳定的资源与项目 scope 前缀保持不变，确保统一失效仍然有效。
- Quickstart 未完成 Catalog 驱动的 Engine 选择前不得猜测或回退到某个默认 Engine；所有请求和创建均使用用户已选的 Catalog Engine ID。
- Agent API 响应必须显式包含非空 `engine_kind`；前端边界解析器拒绝缺失值，编辑页不得用 `claude` 或其他 Engine 静默补齐。
- Agent 创建请求必须显式提交 `engine_kind`，API schema 不提供默认 Engine；前端交互与 API 合约都要求先确定 Engine。
- Agent 显式清空模型配置使用 JSON `null` 并持久化为数据库 `NULL`，不得保存空字符串哨兵。
- Skill AI Authoring 是固定的 `openai_responses` Protocol 消费者，只查询和接受显式 LLM Secret，不允许 Generic Secret 通过 `OPENAI_*` 键名冒充模型配置。
- Quickstart 内联创建取消时返回当前模型配置选择步骤；只有用户主动返回时才回到 Engine 步骤。

## 测试策略

### Catalog 与领域层

- ID 唯一性和引用完整性。
- 初始 Engine 矩阵和 Provider binding。
- `required_any_of`、`base_url_key`、`model_key` 校验。
- 所有 compatibility helper 的排序与错误码。

### 数据库与 Secret API

- 初始 schema 只有一个 Alembic head `20260803_000001`。
- `kind/provider/protocol` 数据库约束。
- 保留名 Provider 被拒绝。
- Generic Secret 不参与 LLM 查询。
- Engine 过滤发生在分页前。
- 默认值按 Protocol 隔离。
- 连接测试只按显式 Provider/Protocol 路由。

### Agent 与 Quickstart

- 创建和更新拒绝不兼容 Secret。
- 同一 Secret 可被多个兼容 Engine 使用。
- Quickstart 与 Agent 使用同一兼容结果和协议适配器。

### 前端

- Engine、Provider、Protocol、Secret 联动。
- 唯一 Protocol 自动选择，多 Protocol 显式选择。
- `values` 在 Profile 变化后无残留字段。
- 连接测试 fingerprint 在任意连接字段变化后失效。
- 创建 Agent 只渲染服务端返回的兼容 Secret。
- 创建流程切换 Engine 不静默替换 Secret。
- 编辑流程保留冲突值并阻止保存。
- Agent 和 Quickstart 原位创建 Secret 不丢表单状态。
- 键盘、焦点、错误提示和小屏幕交互可用。

### Rust 运行时

- Catalog 中每个 Engine/Protocol 关系都有 adapter 覆盖。
- Catalog 中每个 Credential Profile 都有凭据路由覆盖。
- 不支持的组合在解密前失败。
- 日志和错误不包含 Secret 数据。

## 交付顺序

### 第一阶段：领域基线

- 建立 Catalog、领域模型、兼容服务和 Catalog API。
- 直接更新初始 schema、SQLAlchemy model 和 Pydantic schema。
- 建立启动校验与单一 Alembic head 测试。

### 第二阶段：后端闭环

- Secret 创建、过滤、默认值和连接测试切换到 Catalog。
- Agent 创建、更新和模型解析切换到统一兼容服务。
- Quickstart 按 Secret Protocol 分发。
- Rust 在解密前完成同一契约校验。

### 第三阶段：前端统一

- 建立 Catalog client、兼容 Secret hook 和共享选择策略。
- 重构 Secret 创建为 `LlmSecretConfigurator`。
- Agent 与 Quickstart 使用 `CompatibleSecretPicker` 和原位创建子视图。
- Secret 列表和详情展示 Provider、Protocol 与兼容 Engine。

### 第四阶段：整体验证

- 完成 Python、API、前端和 Rust 合约测试。
- 更新 API 与用户教程。
- 执行跨流程验收和可访问性检查。

## 成功标准

1. Secret Provider 只表示真实模型服务商，Engine 名称无法作为 Provider 写入。
2. Engine 支持的 Protocol 只有一个权威 Catalog，并由 Python 与 Rust 测试证明。
3. Provider 与 Engine 只通过 Protocol 产生兼容关系。
4. 创建 Agent 时只能获取和选择兼容 Secret，且过滤发生在分页前。
5. 同一 Secret 可以被多个支持相同 Protocol 的 Engine 复用。
6. Secret 不保存 Engine，Engine 上下文只用于筛选。
7. LLM 与 Generic Secret 的数据约束从初始 schema 即成立。
8. 系统保持单一 Alembic head `20260803_000001`。
9. Agent、Secret、Quickstart 和 Rust 不再各自维护独立兼容规则。
10. 所有兼容判断都基于显式字段，不解密 Secret，也不通过键名或 URL 猜测身份。
11. 切换 Engine 时前端不会静默替换生产 Secret。
12. 用户可在 Agent 或 Quickstart 当前流程内创建模型配置，已填写内容不会丢失。
13. 普通创建流程不要求用户理解环境变量键名。
14. 加载、测试和创建失败均保留合法输入并提供恢复操作。
15. 键盘和小屏幕用户可以完成完整配置流程。
16. Agent 在保存和运行前均通过同一 Catalog 契约校验。
