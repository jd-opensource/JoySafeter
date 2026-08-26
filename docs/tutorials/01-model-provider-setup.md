# 教程 01：引擎、协议、模型供应商与模型配置

JoySafeter 把大模型接入拆成四个明确概念：

```text
Engine --supports--> Protocol <--implements-- Provider
Model Credential = kind + Provider + Protocol + encrypted fields
Agent = Engine + model_credential_id
```

- **Engine（引擎）**：运行 Agent 的执行器，例如 Claude Code、Codex、Native、Pi。
- **Protocol（协议）**：请求与流式响应契约，例如 Anthropic Messages、OpenAI Responses、Chat Completions。
- **Provider（模型供应商）**：实现某个协议的服务商，例如 Anthropic、OpenAI、DeepSeek 或自定义兼容服务。
- **模型连接（Model Credential）**：保存 `kind=model`、`provider`、`protocol` 和对应 Credential Profile 的加密字段。

引擎在开发时通过 Catalog 明确声明支持哪些协议；供应商通过 Catalog 声明实现哪些协议。前后端和运行时都使用同一份 Catalog，不从 Provider 名称或密钥键名猜测兼容性。

## 1. 查看 LLM Catalog

`GET /api/v1/llm/catalog` 返回当前系统支持的引擎、协议、供应商绑定与凭据字段定义。

当前初始矩阵：

| 引擎 | 支持协议 |
|---|---|
| Claude Code (`claude`) | `anthropic_messages` |
| Codex (`codex`) | `openai_responses` |
| Native (`native`) | `anthropic_messages`、`openai_responses`、`chat_completions` |
| Pi (`pi`) | `anthropic_messages`、`openai_responses`、`chat_completions` |

Catalog 是系统契约。新增引擎适配器、协议适配器或供应商绑定时，应先更新 Catalog，再实现对应运行时路由。

## 2. 在界面创建模型连接

进入 **资源 → 凭据**（`/managed/credentials?tab=models`），点击创建：

1. 选择 **模型连接**，而不是服务凭据。
2. 可选择“计划用于哪个引擎”；该选择只筛选兼容项，不会把配置绑定到单个引擎。
3. 选择模型供应商。
4. 当供应商与引擎交集只有一个协议时，系统自动选择；有多个协议时显式选择。
5. 填写 Catalog Credential Profile 展示的字段。
6. 测试连接并创建。

`provider` 和 `protocol` 共同定义连接身份，创建后不可修改。若要切换身份，请创建新的模型连接，再修改 Agent 的 `model_credential_id`。

## 3. 创建 Anthropic 配置

```bash
curl -X POST http://localhost:8000/api/v1/credentials \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <platform-token>" \
  -d '{
    "kind": "model",
    "name": "anthropic-production",
    "provider": "anthropic",
    "protocol": "anthropic_messages",
    "data": {
      "ANTHROPIC_API_KEY": "<secret>",
      "ANTHROPIC_MODEL": "claude-sonnet-4-5"
    },
    "is_default": true
  }'
```

`anthropic_messages` 可用于 Claude Code、Native 和 Pi，不能用于 Codex。

## 4. 创建 OpenAI / OpenAI-compatible 配置

OpenAI Responses：

```bash
curl -X POST http://localhost:8000/api/v1/credentials \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <platform-token>" \
  -d '{
    "kind": "model",
    "name": "openai-production",
    "provider": "openai",
    "protocol": "openai_responses",
    "data": {
      "OPENAI_API_KEY": "<secret>",
      "OPENAI_MODEL": "gpt-5"
    },
    "is_default": true
  }'
```

DeepSeek Chat Completions：

```bash
curl -X POST http://localhost:8000/api/v1/credentials \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <platform-token>" \
  -d '{
    "kind": "model",
    "name": "deepseek-chat",
    "provider": "deepseek",
    "protocol": "chat_completions",
    "data": {
      "OPENAI_API_KEY": "<secret>",
      "OPENAI_MODEL": "deepseek-chat"
    }
  }'
```

默认配置按 **Protocol** 隔离：一个 `anthropic_messages` 默认配置和一个 `openai_responses` 默认配置可以同时存在。

协议默认仅用于界面推荐和首次自动选择。Agent 的 `model_credential_id` 为空时不会在运行时自动套用默认连接，也不会注入模型凭据。

## 5. 查询某个引擎可用的模型配置

Agent 与 Quickstart 不拉取全部 Credential 后在浏览器猜测，而是调用服务端过滤：

```bash
curl 'http://localhost:8000/api/v1/credentials?kind=model&compatible_engine=codex&limit=100' \
  -H "Authorization: Bearer <platform-token>"
```

列表项会返回：

- `kind`
- `provider`
- `protocol`
- `model`
- `compatible_engine_ids`
- `is_default`
- `keys`（只有字段名，不返回明文）

编辑 Agent 时若切换引擎导致当前配置不兼容，页面会保留原配置名称和元数据，要求用户“重新选择模型配置”或“恢复原引擎”，解决前不能保存。

## 6. 服务凭据

非大模型凭据使用：

```json
{
  "kind": "service",
  "name": "github-token",
  "data": { "GITHUB_TOKEN": "<secret>" }
}
```

服务凭据没有 `provider`、`protocol` 或协议默认状态，也不能作为 Agent 的模型连接。

## 7. 运行时行为

运行前会再次校验：

1. Credential 必须是 `kind=model`。
2. Provider 必须实现 Credential 的 Protocol。
3. Agent Engine 必须支持该 Protocol。
4. Credential Profile 必填字段必须完整。
5. 模型名只从 Credential Profile 的 `model_key` 读取。

校验通过后才会解密凭据并注入运行环境。系统不会创建隐式环境变量别名，也不会根据 Provider 名称推断 Engine。

## 下一步

- [教程 04：创建 Agent 并运行](./04-agent-build-and-run.md)
- [API 说明](../api/openapi.md)
- [系统架构](../ARCHITECTURE_CN.md)
