# MCP Tools 格式统一清理总结

## 日期
2024-12-26

## 问题
前端代码中还存在处理旧格式 `uuid::tool_name` 的逻辑，但系统已经统一使用 `server_name::tool_name` 格式。

## 已清理的内容

### 1. 后端 API 响应

**文件**: `backend/app/api/v1/mcp.py`

**改动**:
- 从 `/api/v1/mcp/tools` API 响应中移除了 `serverId` 字段
- 现在只返回 `serverName`, `name`, `description`

**之前**:
```python
all_tools.append({
    "serverId": str(server.id),
    "serverName": server.name,
    "name": tool.mcp_tool_name or tool.name,
    "description": tool.description,
})
```

**现在**:
```python
all_tools.append({
    "serverName": server.name,
    "name": tool.mcp_tool_name or tool.name,
    "description": tool.description,
})
```

### 2. 前端类型定义

**文件**: `frontend/hooks/queries/mcp.ts`

**改动**:
- 从 `McpTool` 接口中移除了 `serverId` 字段

**之前**:
```typescript
export interface McpTool {
  serverId: string
  serverName: string
  name: string
  description?: string
}
```

**现在**:
```typescript
export interface McpTool {
  serverName: string
  name: string
  description?: string
}
```

### 3. 前端 Hook 接口

**文件**: `frontend/hooks/use-mcp-tools.ts`

**改动**:
- 从 `McpToolForUI` 接口中移除了 `serverId` 字段
- 从工具映射逻辑中移除了 `serverId` 的赋值
- 移除了注释中的 "Use serverName instead of serverId"

### 4. 前端组件注释和逻辑

**文件**: `frontend/app/workspace/[workspaceId]/[agentId]/components/BuilderNode.tsx`

**改动**:
- 更新注释：从 `"server_name::tool_name" or "uuid::tool_name"` 改为 `"server_name::tool_name"`
- 优化解析逻辑：从 `parts.length > 1` 改为 `parts.length === 2`（更严格）

**之前**:
```typescript
// Parse MCP tool IDs: format is "server_name::tool_name" or "uuid::tool_name"
const mcpLabels = mcpIds.map(id => {
  const parts = id.split('::')
  return parts.length > 1 ? parts[1] : id
})
```

**现在**:
```typescript
// Parse MCP tool IDs: format is "server_name::tool_name"
const mcpLabels = mcpIds.map(id => {
  const parts = id.split('::')
  return parts.length === 2 ? parts[1] : id
})
```

### 5. 工具字段组件优化

**文件**: `frontend/app/workspace/[workspaceId]/[agentId]/components/fields/ToolsField.tsx`

**改动**:
- 使用 `parseMcpToolId()` 函数替代简单的 `split('::').pop()`
- 更安全的工具名称提取逻辑

**之前**:
```typescript
{uid.split('::').pop()}
```

**现在**:
```typescript
const parsed = parseMcpToolId(toolId)
const displayName = parsed ? parsed.toolName : toolId
{displayName}
```

## 保留的内容

以下使用 `serverId` 的地方是合理的，**应该保留**：

1. **服务器管理 API** (`frontend/hooks/queries/mcp.ts`):
   - `useCreateMcpServer()`, `useUpdateMcpServer()`, `useDeleteMcpServer()` 等
   - 这些函数使用 `serverId` 作为路由参数，是合理的

2. **服务器管理组件**:
   - `components/settings/*.tsx` 中的服务器操作
   - 这些使用 `serverId` 进行服务器级别的操作（创建、更新、删除）

## 统一后的格式

### 工具 ID 格式
- **统一格式**: `server_name::tool_name`
- **不再支持**: `uuid::tool_name` 或任何其他格式

### 相关函数
- `createMcpToolId(serverName, toolName)`: 创建工具 ID
- `parseMcpToolId(toolId)`: 解析工具 ID（返回 `{ serverName, toolName }`）

## 验证

- ✅ 所有相关文件已更新
- ✅ 代码编译通过，无 linter 错误
- ✅ 格式统一为 `server_name::tool_name`
- ✅ 移除了所有对 `uuid::tool_name` 的支持

## 影响范围

- **后端**: API 响应简化，不再返回冗余的 `serverId`
- **前端**: 类型定义简化，组件逻辑更清晰
- **用户体验**: 无影响（格式已经统一）
