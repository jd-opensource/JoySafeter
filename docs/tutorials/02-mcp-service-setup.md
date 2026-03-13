# 教程 02：添加 MCP 服务

> **适合人群**：希望将外部工具（如 Nmap、Nuclei、Burp Suite 扩展等安全工具）通过 MCP 协议集成到 Agent 中的用户。

---

## 场景说明

MCP（Model Context Protocol）是一种让 Agent 调用外部工具的标准协议。本教程通过两个案例实践：

| 案例 | 目标 |
|------|------|
| **案例 A** | 将已有的 MCP 工具目录加载为 Skills，供 Agent 直接调用 |
| **案例 B** | 编写新的 MCP 工具配置，注册为平台工具节点 |

---

## 机制先行：JoySafeter 的 MCP 与 Skills 不是一回事（否则你会越配越乱）

当前教程最大的问题是把两条不同链路混在一起讲：

- **链路 1：本地 skills/ 目录 → convert → converted_skills.json → 前端 Skills 列表**
  这是“把工具能力包装成 Skills 内容/元数据”的导入链路，重点在**内容分发与索引**。
- **链路 2：MCP Server（DB 配置）→ 连接 → 拉取 tools → ToolRegistry 注册 → Graph 节点引用**
  这是“运行时工具系统”，重点在**连接、权限、注册与调用**。

两条链路都能让 Agent“看起来能用工具”，但它们的运行时语义和排障路径完全不同。

---

## MCP 在后端的真实对象模型（你需要知道的 3 个东西）

### 1）MCP Server（数据库对象）

- 存储在表：`mcp_servers`
- 每个用户的 server name 唯一（见索引 `mcp_servers_user_name_unique_idx`）
- API 入口：`backend/app/api/v1/mcp.py`（`/api/v1/mcp/servers`）

> 你在 UI 里“添加 MCP 服务/启用禁用”本质是在增删改这个表的记录。

### 2）ToolRegistry（内存注册表）

MCP tools 不会直接“写死在代码里”，而是在启动或你启用 server 后动态注册到 registry：

- 注册逻辑：`backend/app/core/tools/tool_registry.py`
- MCP tool 的标识格式：`server_name::tool_name`
  代码里有专门的 separator 与 parse（`make_mcp_tool_key` / `parse_mcp_tool_key`）

**关键理解点**：
- `tool.name` 仍然是 MCP 原始工具名（LLM 会看到）
- `tool.label_name` 才是 `server::tool`（用于管理/显示/选择）

### 3）Graph 节点如何引用 MCP 工具

Graph 节点的 tools 配置结构（后端注释写得很直白）：

- `node.data.config.tools = { builtin: string[], mcp: string[] }`
- 其中 `mcp` 数组元素必须是 `${server_name}::${toolName}`

解析与校验入口：
- `backend/app/core/agent/node_tools.py`（解析 `::`、校验 server 是否存在/启用、按 user_id 取工具）

---

## 运行时数据流：为什么“列表里看得到”不代表“运行时能调用”？

当 Agent 执行到某个节点需要工具时，会发生：

1. 从节点配置里拿到 `tools.mcp=[ "server::tool" ]`
2. 解析 server/tool（格式不对会在日志里提示 missing '::'）
3. 若有 `user_id`：会查 DB 里的 server instance，并验证：
   - server 存在
   - server 属于该用户
   - server enabled
4. 从 ToolRegistry 取对应工具对象
5. 工具 entrypoint 才会真正去连接 MCP server 并调用 tool

所以常见误区是：
- “Skills 页面能搜到 nmap” ≠ “MCP server 已连接且 tools 已注册”
- “converted_skills.json 更新了” ≠ “ToolRegistry 里有 MCP tool”

---

## 调试与排障（按层定位，不要靠猜）

### A. 节点配置层（Graph / Agent）
- 确认 node tools 的 mcp 项是否是 `server::tool` 格式
- 任何缺少 `::` 的值都会被当成非 MCP tool，导致解析失败

### B. Server 层（DB 记录是否存在/启用）
- `GET /api/v1/mcp/servers` 查看该用户下 server 是否 enabled

### C. 注册层（Registry 是否已注册工具）
- 启动时会尝试初始化：`initialize_mcp_tools_on_startup`（`backend/app/services/tool_service.py`）
- 若你新增 server 但没触发注册，通常是连接失败或 server disabled

### D. 连接层（MCP 端点是否可用）
- 用 `/api/v1/mcp/test-connection`（若 UI 有按钮，对应后端会走 `McpClientService.test_connection`）
- 连接参数由 `McpClientService.config_from_server(server)` 生成

---

## 安全边界（必读）：MCP 工具不是“技能文档”，而是“可执行能力”

1. MCP tool 本质是“可执行外部命令/网络请求”的能力。把它暴露给 Agent 之前，至少要明确：
   - 目标是否授权（尤其是扫描/爆破/利用类工具）
   - 是否需要人工确认（Human-in-the-loop）
   - 是否需要沙箱/网络隔离（避免越权访问内网资源）

2. “仅在 manifest.md 写 Safety Notes”是不够的
   安全策略必须落到：
   - 工具注册时的 `requires_confirmation`（如果你有这类机制）
   - 或 Graph 节点中断（教程 05 里会讲）
   - 或服务端对高危工具做 allowlist + 审计日志


---

## 真实可跑：用 JoySafeter 自己的 MCP API 接入一个 MCP Server（端到端示例）

> 目的：给出“能跑”的最小闭环：**创建 server → 测试连接 → 刷新/列出 tools → 节点引用格式 → 执行**。
> 你可以先不改任何前端代码，直接用 curl 验证 MCP 链路打通。

### 前置：你需要一个可访问的 MCP Server URL（streamable-http）

JoySafeter 后端默认支持 `streamable-http` transport（见 `backend/app/api/v1/mcp.py` 的请求 schema），因此你需要一个 MCP Server 提供 HTTP 端点，例如：

- `http://127.0.0.1:9000/mcp`（本机服务）
- `http://<intranet-host>:<port>/mcp`（内网服务）

> 重要：该 URL 必须能从 **JoySafeter 后端容器/进程**访问到（不是从浏览器访问到即可）。

### 步骤 0：创建前先测试连接（不落库）

对应后端：`POST /api/v1/mcp/test`（见 `backend/app/api/v1/mcp.py:test_connection`）

```bash
curl -X POST http://localhost:8000/api/v1/mcp/test \
  -H "Content-Type: application/json" \
  -d '{
    "transport": "streamable-http",
    "url": "http://127.0.0.1:9000/mcp",
    "timeout": 30000,
    "headers": {}
  }'
```

若返回 `data.success=true` 且 `data.tools` 非空，说明“网络可达 + 协议/端点正确”。

### 步骤 1：创建 MCP Server（写入 mcp_servers 表）

对应后端：`POST /api/v1/mcp/servers`（见 `backend/app/api/v1/mcp.py:create_mcp_server`）

```bash
curl -X POST http://localhost:8000/api/v1/mcp/servers \
  -H "Content-Type: application/json" \
  -d '{
    "name": "local-mcp",
    "description": "Local MCP server for testing",
    "transport": "streamable-http",
    "url": "http://127.0.0.1:9000/mcp",
    "headers": {},
    "timeout": 30000,
    "retries": 3,
    "enabled": true
  }'
```

返回 `data.serverId`。

### 步骤 2：测试已创建服务器连接（落库对象）

对应后端：`POST /api/v1/mcp/servers/{server_id}/test`

```bash
curl -X POST http://localhost:8000/api/v1/mcp/servers/<serverId>/test
```

关注：`toolCount`、`tools`、`latencyMs`、失败时的 message。

### 步骤 3：刷新并列出工具（注册到 ToolRegistry）

对应后端：
- `POST /api/v1/mcp/servers/{server_id}/refresh`
- `GET /api/v1/mcp/servers/{server_id}/tools`

```bash
curl -X POST http://localhost:8000/api/v1/mcp/servers/<serverId>/refresh
curl http://localhost:8000/api/v1/mcp/servers/<serverId>/tools
```

### 步骤 4：确认 Graph/节点引用格式（必须是 server::tool）

JoySafeter 解析 MCP tool id 的规则是：

```
<server_name>::<tool_name>
```

这是后端硬性要求（见 `backend/app/core/agent/node_tools.py` 与 `backend/app/core/tools/tool_registry.py`）。

示例：

```
local-mcp::nmap_scan
```

### 步骤 5：直接执行 MCP 工具（不经过 Graph，用于最小闭环验证）

对应后端：`POST /api/v1/mcp/tools/execute`（见 `backend/app/api/v1/mcp.py:execute_tool`）

```bash
curl -X POST http://localhost:8000/api/v1/mcp/tools/execute \
  -H "Content-Type: application/json" \
  -d '{
    "serverName": "local-mcp",
    "toolName": "nmap_scan",
    "arguments": {
      "target": "127.0.0.1",
      "ports": "22,80,443"
    }
  }'
```

如果这一步成功，说明：
- server instance 能正确解析（存在、属于你、enabled）
- tool 已在 ToolRegistry 中注册
- tool entrypoint 能连通 MCP server 并完成调用

---

## 常见问题

### Q：工具加载后在 Skills 列表找不到？

1. 检查 `frontend/public/converted_skills.json` 是否存在
2. 清除 LocalStorage：DevTools → Application → Local Storage → 删除 `joysafeter_skills`
3. 刷新页面

### Q：如何给工具添加安全检查？

在 `manifest.md` 中添加 `requires_authorization: true` 字段，并在工具实现中加入授权校验逻辑。

### Q：MCP 工具和普通 Skill 有什么区别？

MCP 工具通过标准化 manifest 格式定义参数和能力，可以被 Agent 自动解析并调用；普通 Skill 更灵活，支持自由定义内容和文件结构。

---

## 下一步

- 参考教程 03：导入 Skills，了解如何批量导入社区 Skills
- 参考教程 04：构建 Graph，将 MCP 工具集成到工作流节点中
