# MCP Tools 重构总结 - 方案A实施

## 实施日期
2024-12-26

## 目标
统一使用 ToolRegistry 管理 MCP 工具，移除双重工具获取机制。

## 已完成的改动

### 1. 修改 `resolve_tools_for_node()` 从 ToolRegistry 读取工具

**文件**: `backend/app/core/agent/node_tools.py`

**改动**:
- 移除了对 `get_mcp_tools()` 的调用（之前使用 `MultiServerMCPClient` 直接连接）
- 改为从 `ToolRegistry` 读取工具，使用 `registry.get_mcp_tool(server_name, tool_name)`
- 添加了 `_validate_mcp_servers()` 函数来验证服务器是否存在且启用（但不连接）
- 移除了 `_resolve_mcp_servers()` 函数（不再需要解析 URL 和 transport）
- 移除了 `_build_mcp_servers_config()` 函数（不再需要构建 MultiServerMCPClient 配置）

**关键变化**:
```python
# 之前：直接连接 MCP 服务器
mcp_tools = await get_mcp_tools(_build_mcp_servers_config(resolved_map))

# 现在：从 Registry 读取
registry = get_global_registry()
tool = registry.get_mcp_tool(server_name, tool_name)
```

### 2. 更新 `get_agent()` 函数

**文件**: `backend/app/core/agent/sample_agent.py`

**改动**:
- 移除了 `tools is None` 时调用 `get_mcp_tools()` 的逻辑
- 改为返回空列表（工具应该通过 `resolve_tools_for_node()` 显式提供）

### 3. 删除废弃的函数

**文件**: `backend/app/core/agent/sample_agent.py`

**改动**:
- 完全删除了 `get_mcp_tools()` 函数（不再需要）
- 移除了相关的缓存代码和 `MultiServerMCPClient` 导入
- 移除了废弃注释

### 4. 清理未使用的导入

**文件**:
- `backend/app/core/agent/sample_agent.py`: 移除 `asyncio`, `json`, `MultiServerMCPClient`
- `backend/app/core/agent/node_tools.py`: 移除 `Tuple` 类型导入

## 验证

### 已验证的功能

1. ✅ 工具执行 API (`/api/v1/mcp/tools/execute`) 已正确使用 Registry
2. ✅ `resolve_tools_for_node()` 现在从 Registry 读取工具
3. ✅ 代码编译通过，无 linter 错误

### 工具注册流程（保持不变）

工具注册到 Registry 的流程仍然正常工作：
- `ToolService.create_mcp_server()` → `_sync_server_tools()` → `ToolRegistry.register_mcp_tools()`

## 待完成的工作

### 已完成的额外清理

1. ✅ **完全移除 `get_mcp_tools()` 函数**
   - 已确认没有外部依赖
   - 函数已完全删除

2. **移除 `MultiMCPTools` 类**
   - 文件：`backend/app/core/tools/mcp/multi_mcp.py`
   - 完全未被使用，可以删除

3. **简化 `MCPTools` 类**
   - 文件：`backend/app/core/tools/mcp/mcp.py`
   - 仅在注册时使用，可以简化或重构

## 架构变化

### 之前（双重机制）

```
添加: MCPTools → Registry（注册但不使用）
使用: MultiServerMCPClient → 直接连接（绕过 Registry）
```

### 现在（统一机制）

```
添加: MCPTools → Registry（注册）
使用: Registry → 读取工具（统一使用 Registry）
```

## 优点

1. ✅ **统一管理**: 所有工具通过 Registry 统一管理
2. ✅ **避免重复连接**: 工具在注册时连接一次，后续从 Registry 读取
3. ✅ **前后端一致**: 前端查询和执行 API 都使用 Registry，与实际执行路径一致
4. ✅ **代码简化**: 移除了大量冗余代码

## 注意事项

1. **工具必须已注册**: 工具必须先通过 `ToolService` 注册到 Registry，否则无法使用
2. **连接生命周期**: MCP 连接在工具注册时建立，需要确保连接保持可用
3. **完全移除**: `get_mcp_tools()` 函数已完全删除，不再提供向后兼容

## 测试建议

1. 测试 MCP 服务器创建和工具注册
2. 测试 Graph 节点使用 MCP 工具
3. 测试工具执行 API
4. 测试前端工具查询和选择功能
