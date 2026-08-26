# 教程 02：为 Agent 接入 MCP 工具

> **适合人群**：希望把外部工具（如安全扫描器、内部服务）通过 MCP 协议提供给 Agent 的用户。

---

## 机制先行：MCP 是 Agent 配置的一部分

- **MCP 服务器定义** 通过 Agent API 的 `mcp_servers` 配置，在 **Agent 编辑器**里编辑
  （前端表现为 `mcp_toolset` 工具项，带 `permission_policy`）。远程服务器只接受
  `streamable_http` / `sse` 与 `name`、`url`、`auth_requirement`；本地进程只接受
  `local_stdio` 与 `name`、`command`、`args`、`env`。旧别名不会在运行时兼容。
- **MCP 凭据** 存在项目级 **MCP 凭据组**（`joysafeter_credential_groups` / `joysafeter_credentials`，
  API `/api/v1/credential-groups`，UI **托管智能体 → 凭据**）：按规范化 MCP server URL 匹配，支持
  `static_bearer`、`header_api_key`、`custom_header` 三种加密头凭据。历史 MCP OAuth 仅保留为
  不可恢复、不可激活的停用记录。
- **Session 授权** 通过 `credential_group_ids` 选择本次运行可用的凭据组。凭据组不会创建 MCP 连接，
  也不会永久绑定到 Agent；Agent 中必须先存在对应服务器声明。

**运行时如何生效**：任务调度时，orchestrator：
1. 从 Agent 的 `mcp_servers` 取 MCP 服务器列表；
2. 由 MCP runtime planner 按 URL 和 `auth_requirement` 解析凭据，生成 runner-safe 配置与仅供 Envoy
   使用的凭据头；明文凭据不会进入 gRPC 或 runner；
3. 单一 Lease-elected xDS authority 发布对应 generation，并在 Envoy ACK 且 PostgreSQL 状态变为
   `ready` 后允许任务启动；
4. 把不含凭据的结果作为 `McpConfig` 经 gRPC 下发给 runner；runner 再投影为 Claude/Codex harness
   各自需要的配置格式。

> “工具能不能用”取决于：**Agent 是否配置该 server、`auth_requirement` 是否满足、当前网络模式是否
> 允许、且该 generation 是否已被 Envoy ACK 并持久化为 `ready`**。

---

## 案例 A：给 Agent 加一个 HTTP（streamable）MCP 服务器

1. 进入 **托管智能体 → 智能体**（`/managed/agents`），打开目标 Agent 的 **编辑器**。
2. 在 **MCP 服务器**区域新增一条：
   - `name`：`recon-mcp`
   - 类型：HTTP / streamable（URL 型）
   - `url`：`http://recon-mcp.internal:9000/mcp`
   - `auth_requirement`：无需认证选 `none`；需要认证选 `required` 或 `optional`
3. 保存 Agent。

> URL 必须能从**沙箱容器**访问到，且其域名要在 Envoy 出口白名单内（沙箱默认全拒出口）。
> 当前 `sse` 只支持 `auth_requirement: none`；托管凭据注入仅支持 `streamable_http`。

## 案例 B：给需要鉴权的 MCP 服务器在 MCP 凭据组中配置凭据

1. 进入 **托管智能体 → 凭据 → MCP**（`/managed/credentials?tab=mcp`），新建一个 Credential Group，再在其下新建一条 **MCP 凭据**：
   - `mcp_server_url`：与上面 Agent 里的 MCP `url` 一致（用于运行时匹配）
   - `auth_scheme`：`static_bearer`、`header_api_key` 或 `custom_header`
   - `data.token_value`：凭据值（**加密存储**）
   - `data.header_name`：后两种方案必填；`custom_header` 还可提供 `data.value_prefix`
2. 创建 Session 时选择该 Credential Group（Session 的 `credential_group_ids`）。

Session 创建前会逐个检查 Agent 远程 MCP 服务器：`required` 必须恰好匹配一条活动凭据，`optional`
允许无凭据运行或匹配一条，`none` 永不注入。未被 Agent 声明的凭据 URL 不参与冲突检查。

CLI 使用相同规则：

```bash
# 交互查看每个 endpoint 的覆盖状态，并按需选择或创建凭据组
joysafeterctl create session

# 非交互创建聊天 Session；参数可重复
joysafeterctl chat --agent my-agent \
  --credential-group credgrp_00000000-0000-0000-0000-000000000001

# 完整向导会在 Agent 之后单独进入 MCP Access 步骤
joysafeterctl init
```

`chat --agent` 在终端中未显式传组时会进入引导；在非交互环境中不会猜测凭据，若 `required`
endpoint 未覆盖会给出可操作错误。CLI 创建 MCP 凭据时使用隐藏输入，并支持 Bearer、API-key header
与 custom header。

运行时 orchestrator 会按 `mcp_server_url` 把凭据头只注入 Envoy 到目标 MCP 服务器的请求，
你无需把明文凭据写进 Agent 配置，runner 也不会收到明文。

---

## 三类工具能力的边界

Agent 的“工具”来自三处（都在 Agent 编辑器配置，运行时经 gRPC 下发给沙箱 runner）：

| 来源 | 配置位置 | 载荷（gRPC） |
|------|---------|-------------|
| 内置工具 + 工具策略 | Agent 编辑器：内置工具勾选 + 每工具 `permission_policy`（`always_ask` / `always_allow`） | `allowed_tools` / `disallowed_tools` / `ask_tools` |
| MCP 服务器 | Agent `mcp_servers` + MCP 凭据组中的凭据 | `McpConfig`（typed transport；无凭据头） |
| 自定义工具 | Agent 编辑器：自定义工具（名称 + 描述 + JSON Schema） | `CustomTool` |

---

## 安全边界（必读）

MCP 工具是**可执行的外部能力**（尤其安全扫描 / 利用类）。平台提供的控制点：

- **工具授权策略**：把高危工具设为 `always_ask`（`ask_tools`），触发时会作为 `is_control_request`
  的 tool_use 事件回到前端，需人工确认后 orchestrator 才用 `SendInput` 放行。
- **沙箱隔离**：每个会话独享一个加固沙箱（丢弃能力、非 root、Envoy 出口白名单），即便工具高危，
  影响也被限制在该沙箱内。
- **凭据隔离**：MCP token 放 MCP 凭据组加密存储，运行时才注入请求头，不落 Agent 明文、不进事件流。
- **本地配置边界**：`local_stdio.env` 不经过凭据系统，不应填写 token、密码或 API Key。

---

## 下一步

- [教程 03](./03-skills-usage.md)：导入 Skills（技能包），与 MCP 工具互补
- [教程 04](./04-agent-build-and-run.md)：构建并运行一个带工具 / MCP / 技能的 Agent
