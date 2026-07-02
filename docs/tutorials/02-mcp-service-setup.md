# 教程 02：为 Agent 接入 MCP 工具

> **状态：** 已按 v2 真实代码核对（2026-07-02）。
> **适合人群**：希望把外部工具（如安全扫描器、内部服务）通过 MCP 协议提供给 Agent 的用户。

---

## 机制先行：v2 没有独立的 MCP 服务注册中心

v1 的 `mcp_servers` 表、`/api/v1/mcp/*` 系列端点、内存 `ToolRegistry`、`server::tool` 键、
以及“把 MCP 挂到 Graph 节点”的整套东西**都已移除**。v2 里 MCP 是 **Agent 配置的一部分**：

- **MCP 服务器定义** 存在 Agent 行的 `mcp_configs`（JSONB 数组），在 **Agent 编辑器**里编辑
  （前端表现为 `mcp_toolset` 工具项，带 `permission_policy`）。每条包含 `name`、连接方式
  （命令 / URL）、`server_type`、`headers` 等。
- **MCP 凭据** 存在 **Vaults**（`joysafeter_vaults` / `joysafeter_vault_credentials`，
  API `/api/v1/vaults`，UI `/managed/vaults`）：加密的 token / OAuth 配置，按 MCP server URL 匹配。

**运行时如何生效**：任务调度时，orchestrator：
1. 从 Agent 的 `mcp_configs` 取 MCP 服务器列表；
2. 调 `VaultService.resolve_mcp_credentials(...)` 按 URL 匹配 Vault 凭据，注入 `Authorization: Bearer`
   头（OAuth 临期会自动刷新）；
3. 把结果作为 `McpConfig` 消息经 gRPC `SetupSandbox` / `StartTask` 下发给沙箱内的 runner；
4. runner 把 MCP 配置写入沙箱内的 `.claude/settings.json`（Claude 引擎），CLI harness 据此连接 MCP
   服务器并调用工具。

> 所以“工具能不能用”不再取决于某个中心注册表，而取决于：**该 Agent 的 `mcp_configs` 里有没有这条
> server + Vault 里有没有对应凭据 + 沙箱能否网络到达该 MCP 端点（Envoy 出口白名单）**。

---

## 案例 A：给 Agent 加一个 HTTP（streamable）MCP 服务器

1. 进入 **Build → Agents**，打开目标 Agent 的 **编辑器**。
2. 在 **MCP 服务器**区域新增一条：
   - `name`：`recon-mcp`
   - 类型：HTTP / streamable（URL 型）
   - `url`：`http://recon-mcp.internal:9000/mcp`
3. 保存 Agent。（这条会写进该 Agent 的 `mcp_configs` JSONB。）

> URL 必须能从**沙箱容器**访问到，且其域名要在 Envoy 出口白名单内（沙箱默认全拒出口）。

## 案例 B：给需要鉴权的 MCP 服务器配置 Vault 凭据

1. 进入 **Build → Vaults**，新建一个 Vault，再在其下新建一条 **Credential**：
   - `mcp_server_url`：与上面 Agent 里的 MCP `url` 一致（用于运行时匹配）
   - `credential_type`：`static_bearer`（或 OAuth 配置）
   - `token_value`：你的 Bearer token（**加密存储**）
2. 在会话 / Agent 上关联该 Vault（会话的 `vault_ids`）。

运行时 orchestrator 会按 `mcp_server_url` 把这条凭据的 Bearer 注入到对该 MCP 服务器的请求头，
你无需把明文 token 写进 Agent 配置。

---

## 三类工具能力的边界

v2 里 Agent 的“工具”来自三处（都在 Agent 编辑器配置，运行时经 gRPC 下发给沙箱 runner）：

| 来源 | 配置位置 | 载荷（gRPC） |
|------|---------|-------------|
| 内置工具 + 工具策略 | Agent 编辑器：内置工具勾选 + 每工具 `permission_policy`（`always_ask` / `always_allow`） | `allowed_tools` / `disallowed_tools` / `ask_tools` |
| MCP 服务器 | Agent `mcp_configs` + Vault 凭据 | `McpConfig`（name/command/args/url/headers…） |
| 自定义工具 | Agent 编辑器：自定义工具（名称 + 描述 + JSON Schema） | `CustomTool` |

---

## 安全边界（必读）

MCP 工具是**可执行的外部能力**（尤其安全扫描 / 利用类）。v2 提供的控制点：

- **工具授权策略**：把高危工具设为 `always_ask`（`ask_tools`），触发时会作为 `is_control_request`
  的 tool_use 事件回到前端，需人工确认后 orchestrator 才用 `SendInput` 放行。
- **沙箱隔离**：每个会话独享一个加固沙箱（丢弃能力、非 root、Envoy 出口白名单），即便工具高危，
  影响也被限制在该沙箱内。
- **凭据隔离**：MCP token 放 Vault 加密存储，运行时才注入请求头，不落 Agent 明文、不进事件流。

---

## 常见问题

**Q：以前的 `/api/v1/mcp/test` / `refresh` / `tools/execute` 还在吗？**
不在。v2 没有独立 MCP 端点；MCP 随 Agent 配置在会话启动时下发给沙箱，工具的连通性在实际会话里体现。

**Q：`server::tool` 这种引用格式呢？**
已废弃——v2 不再有 Graph 节点按 `server::tool` 引用工具的机制。工具集由 Agent 配置整体下发。

---

## 下一步

- [教程 03](./03-skills-usage.md)：导入 Skills（技能包），与 MCP 工具互补
- [教程 04](./04-agent-build-and-run.md)：构建并运行一个带工具 / MCP / 技能的 Agent
