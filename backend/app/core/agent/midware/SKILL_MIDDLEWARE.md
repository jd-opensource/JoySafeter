# Skill Middleware 使用说明

## 概述

Skill Middleware 实现了**渐进式技能披露（Progressive Disclosure）**模式，允许 Agent 按需加载技能内容，而不是一次性加载所有技能信息。这种方式可以：

- **减少上下文使用**：只加载当前任务需要的 2-3 个技能，而不是所有可用技能
- **提高可扩展性**：可以添加数十或数百个技能而不会使上下文窗口过载
- **简化对话历史**：单一 Agent 使用一个对话线程
- **支持团队自治**：不同团队可以独立开发和维护专业技能

## 架构设计

### 分层架构

```
Middleware Layer (SkillsMiddleware)
    ↓ 读取预加载文件
Sandbox Backend (/workspace/skills/)
    ↓ 预加载
Service Layer (SkillService)
    ↓
Repository Layer (SkillRepository)
    ↓
Database (PostgreSQL)
```

**注意**：详细架构设计请参考 [Skill 架构文档](../../skill/ARCHITECTURE.md)

### 工作流程

```mermaid
graph TD
    A[构建 Agent] --> B[SkillSandboxLoader 预加载技能文件]
    B --> C[文件写入 /workspace/skills/]
    C --> D[Agent with SkillsMiddleware]
    D --> E[系统提示注入技能描述]
    E --> F[用户请求]
    F --> G[Agent 决定需要技能]
    G --> H[Agent 直接读取沙箱文件]
    H --> I[/workspace/skills/skill-name/SKILL.md]
    I --> J[Agent 使用技能完成任务]
```

## 核心组件

### 1. SkillsMiddleware (deepagents)

技能中间件使用系统库 `deepagents.middleware.skills.SkillsMiddleware`，负责：
- 在 `before_agent` 钩子中从 BackendProtocol 加载可用技能列表
- 在 `wrap_model_call` 中将技能描述注入系统提示
- 支持多个 sources，后面的源覆盖前面的同名技能
- 技能必须预加载到 `/workspace/skills/` 目录（通过 `SkillSandboxLoader`）

### 2. SkillSandboxLoader

**位置**：`core/skill/sandbox_loader.py`

负责在构建时预加载技能文件到沙箱：
- 从数据库加载技能及其文件
- 将文件写入 `/workspace/skills/{skill_name}/` 目录
- 支持增量加载（避免重复加载已存在的技能）
- 在 DeepAgents 构建时自动调用

**预加载时机**：
- DeepAgents 构建时：通过 `_preload_skills_to_backend` 自动预加载
- 常规 Agent：如果配置了技能，也会在构建时预加载

### 3. Agent 直接读取文件

**重要**：Agent 应该直接读取沙箱中的技能文件，而不是通过工具加载。

技能文件结构：
```
/workspace/skills/
├── skill-name-1/
│   ├── SKILL.md          # 技能说明（包含 Instructions）
│   ├── file1.py
│   └── subdir/
│       └── file2.py
└── skill-name-2/
    └── SKILL.md
```

Agent 读取方式：
1. **读取 SKILL.md 获取 Instructions**：
   ```python
   # Agent 可以通过 FilesystemMiddleware 读取
   content = read_file("/workspace/skills/pdf-skill/SKILL.md")
   ```

2. **读取其他文件**：
   ```python
   # Agent 可以根据需要读取技能的其他文件
   code = read_file("/workspace/skills/pdf-skill/utils.py")
   ```

**为什么直接读取文件？**
- ✅ 文件已经预加载到沙箱，无需重复加载
- ✅ 架构更清晰：预加载阶段和运行时阶段分离
- ✅ 性能更好：避免数据库查询和格式化开销
- ✅ Agent 可以按需读取，只加载需要的文件

### 4. SkillFormatter

**位置**：`core/skill/formatter.py`

技能内容格式化器，纯函数实现：
- `format_skill_content()`: 格式化单个技能内容
- `format_skill_list()`: 格式化技能列表为 Markdown
- 无副作用，可独立测试

### 5. SkillService

服务层提供以下方法：
- `list_skills()`: 获取用户可访问的技能列表
- `get_skill_by_name()`: 根据名称查找技能（不区分大小写）
- `format_skill_content()`: 格式化技能内容为字符串（使用 `SkillFormatter`，主要用于 API 响应）

## 使用方法

### 1. 在常规 Agent 中启用技能

```python
from app.core.agent.sample_agent import get_agent
from app.core.database import async_session_factory

# 创建带技能支持的 Agent
agent = await get_agent(
    user_id="user-123",
    enable_skills=True,  # 启用技能中间件（默认 True）
    skill_user_id="user-123",  # 技能过滤的用户ID（默认使用 user_id）
    # ... 其他参数
)
```

### 2. 在 Deep Agents 中启用技能

Deep Agents 会自动为所有节点（Manager 和 Worker）启用技能支持：

```python
from app.core.graph.deep_agents_builder import DeepAgentsGraphBuilder

builder = DeepAgentsGraphBuilder(
    graph=graph,
    nodes=nodes,
    edges=edges,
    user_id="user-123",
    # ... 其他参数
)

# 构建时自动集成技能中间件
agent_graph = await builder.build()
```

### 3. 创建技能

通过 API 创建技能：

```python
POST /api/v1/skills
{
    "name": "pdf-skill",
    "description": "处理 PDF 文件的专业技能",
    "content": "# PDF 处理技能\n\n## 功能\n- 解析 PDF 内容\n- 提取文本\n- 处理表格数据",
    "tags": ["pdf", "document"],
    "is_public": false
}
```

### 4. Agent 使用技能

Agent 会自动看到可用技能的描述，并直接读取沙箱中的文件：

```
用户: 帮我处理这个 PDF 文件

Agent: 我看到有一个 pdf-skill 技能可以处理 PDF 文件。
      让我读取这个技能的详细说明...

[Agent 读取 /workspace/skills/pdf-skill/SKILL.md]

Agent: 已读取 PDF 处理技能说明。现在我可以：
      - 解析 PDF 内容
      - 提取文本
      - 处理表格数据

      请提供 PDF 文件路径...
```

**Agent 读取技能文件的步骤**：
1. SkillsMiddleware 已在系统提示中注入技能描述
2. Agent 根据描述决定使用哪个技能
3. Agent 通过 FilesystemMiddleware 读取 `/workspace/skills/{skill_name}/SKILL.md`
4. Agent 根据需要读取其他文件（如 Python 代码、配置文件等）
5. Agent 使用技能完成任务

## 配置选项

### SkillMiddleware 参数

```python
from deepagents.middleware.skills import SkillsMiddleware

# SkillsMiddleware 需要 backend 和 sources
middleware = SkillsMiddleware(
    backend=backend,  # BackendProtocol 实例
    sources=["/workspace/skills/"],  # 技能源路径列表
)
```

如果没有 backend，可以使用适配器：

```python
from app.core.agent.midware.skill_adapter import DatabaseSkillAdapter

middleware = DatabaseSkillAdapter(
    user_id="user-123",  # 用户ID，用于过滤技能
    skill_ids=[uuid1, uuid2],  # 可选：特定技能ID列表
    db_session_factory=async_session_factory,  # 数据库会话工厂
)
```

**SkillsMiddleware 参数说明：**

- `backend` (BackendProtocol): 必需，后端协议实例，用于读取技能文件
- `sources` (List[str]): 必需，技能源路径列表，例如 `["/workspace/skills/"]`
  - 技能必须通过 `SkillSandboxLoader` 预加载到这些路径
  - 支持多个源，后面的源覆盖前面的同名技能

**DatabaseSkillAdapter 参数说明：**

- `user_id` (Optional[str]): 用户ID，用于过滤用户可访问的技能
  - 如果为 `None`，只加载公开技能
  - 如果提供，加载用户自己的技能和公开技能

- `skill_ids` (Optional[List[UUID]]): 可选，特定技能ID列表
  - 如果提供，只加载指定的技能
  - 如果为 `None`，加载所有可访问的技能

- `db_session_factory` (Optional[Callable]): 异步数据库会话工厂
  - 默认使用 `async_session_factory`
  - 用于创建数据库会话以查询技能

- `backend_factory` (Optional[Callable]): 后端工厂函数
  - 默认使用 `StateBackend`
  - 用于创建临时后端存储技能文件

### 默认系统提示模板

```python
"""
## Available Skills

{skills_prompt}

When you need detailed information about a skill, read the skill files
directly from /workspace/skills/{skill_name}/. Start with SKILL.md for
instructions, then read other files as needed.
"""
```

## 技能数据结构

### Skill 模型

```python
{
    "id": "uuid",
    "name": "skill-name",  # 技能名称（唯一标识）
    "description": "简短描述",  # 显示在系统提示中
    "content": "完整内容...",  # SKILL.md 的 body 部分（Instructions）
    "tags": ["tag1", "tag2"],
    "is_public": false,
    "owner_id": "user-id",
    "files": [...]  # 关联的文件
}
```

### 技能文件结构

技能文件预加载到沙箱后的结构：

```
/workspace/skills/pdf-skill/
├── SKILL.md              # 技能说明文件（包含 Instructions）
├── utils.py              # 工具函数
└── examples/
    └── example.pdf       # 示例文件
```

**SKILL.md 格式**：
```markdown
---
name: pdf-skill
description: 处理 PDF 文件的专业技能
tags: [pdf, document]
---

# PDF 处理技能

## 功能
- 解析 PDF 内容
- 提取文本
- 处理表格数据

## 使用方法
...
```

Agent 应该：
1. 读取 `/workspace/skills/{skill_name}/SKILL.md` 获取完整说明
2. 根据需要读取其他文件（如 Python 代码、配置文件等）
3. 使用技能完成任务

## 权限控制

技能系统遵循以下权限规则：

1. **私有技能**：只有拥有者可以访问
2. **公开技能**：所有用户都可以访问
3. **系统技能**：`owner_id` 为 `None` 的技能，所有用户可访问

权限检查在 `SkillService` 层进行，确保 Agent 只能访问有权限的技能。

## Agent 读取技能文件

### 文件读取方式

Agent 应该通过 FilesystemMiddleware 直接读取沙箱中的技能文件：

```python
# 读取技能说明
skill_instructions = read_file("/workspace/skills/pdf-skill/SKILL.md")

# 读取其他文件
utility_code = read_file("/workspace/skills/pdf-skill/utils.py")
```

### 文件路径规范

技能文件预加载后的路径结构：
- 技能根目录：`/workspace/skills/{skill_name}/`
- 技能说明：`/workspace/skills/{skill_name}/SKILL.md`
- 其他文件：`/workspace/skills/{skill_name}/{relative_path}`

### 预加载保证

**重要**：所有技能都会在 Agent 构建时通过 `SkillSandboxLoader` 预加载到沙箱：
- DeepAgents：在 `_preload_skills_to_backend` 中自动预加载
- 常规 Agent：如果配置了技能，也会在构建时预加载
- 支持增量加载：已加载的技能不会重复加载

## 故障排除

### 1. 技能未加载

**问题**：Agent 看不到可用技能

**解决方案**：
- 检查 `enable_skills` 参数是否为 `True`
- 确认 `user_id` 正确设置
- 检查数据库中是否有可访问的技能（用户自己的或公开的）

### 2. 技能文件未找到

**问题**：Agent 无法读取 `/workspace/skills/{skill_name}/SKILL.md`

**可能原因**：
- 技能未预加载到沙箱
- 技能名称拼写错误
- 用户没有访问该技能的权限

**解决方案**：
- 检查技能是否在节点配置中正确配置（`config.skills`）
- 确认 `SkillSandboxLoader` 已成功预加载技能
- 检查日志中是否有预加载错误信息
- 确认技能是公开的或属于当前用户

### 3. 技能文件读取失败

**问题**：Agent 无法读取技能文件

**可能原因**：
- FilesystemMiddleware 未启用
- 文件路径错误
- 权限问题

**解决方案**：
- 确保 FilesystemMiddleware 已添加到 Agent 中间件列表
- 检查文件路径是否正确（使用 `/workspace/skills/{skill_name}/SKILL.md`）
- 确认 backend 已正确创建并启动

### 4. 技能内容过长

**问题**：技能内容超过上下文限制

**解决方案**：
- 将大技能拆分为多个小技能
- 使用技能文件存储详细内容
- 考虑使用分页加载（未来功能）

## 最佳实践

### 1. 技能命名

- 使用清晰、描述性的名称
- 使用小写字母和连字符：`pdf-skill`, `sql-query`, `data-analysis`
- 避免使用特殊字符和空格

### 2. 技能描述

- 保持简短（1-2 句话）
- 明确说明技能的用途
- 帮助 Agent 判断是否需要加载该技能

### 3. 技能内容

- 结构化组织内容（使用 Markdown）
- 提供清晰的指令和示例
- 包含相关的业务逻辑和规则

### 4. 技能文件

- 将大型内容存储在技能文件中
- 使用适当的文件类型标识
- 保持文件内容简洁明了

## 示例

### 完整示例：SQL 查询助手

```python
# 1. 创建技能
skill_data = {
    "name": "sales-analytics",
    "description": "销售数据分析的数据库模式和业务逻辑",
    "content": """# Sales Analytics Schema

## Tables

### customers
- customer_id (PRIMARY KEY)
- name
- email
- signup_date
- status (active/inactive)
- customer_tier (bronze/silver/gold/platinum)

### orders
- order_id (PRIMARY KEY)
- customer_id (FOREIGN KEY -> customers)
- order_date
- status (pending/completed/cancelled/refunded)
- total_amount
- sales_region (north/south/east/west)

## Business Logic

**Active customers**: status = 'active' AND signup_date <= CURRENT_DATE - INTERVAL '90 days'

**Revenue calculation**: Only count orders with status = 'completed'
""",
    "tags": ["sql", "sales", "analytics"],
    "is_public": True
}

# 2. 创建 Agent
agent = await get_agent(
    user_id="user-123",
    enable_skills=True,
    system_prompt="You are a SQL query assistant."
)

# 3. Agent 自动使用技能
result = await agent.ainvoke({
    "messages": [{
        "role": "user",
        "content": "Write a SQL query to find all active customers who made orders over $1000"
    }]
})

# Agent 会：
# 1. 看到 "sales-analytics" 技能描述（通过 SkillsMiddleware）
# 2. 读取 /workspace/skills/sales-analytics/SKILL.md 获取完整说明
# 3. 获取完整的数据库模式和业务逻辑
# 4. 编写正确的 SQL 查询
```

## API 参考

### SkillSandboxLoader 类

**位置**：`app.core.skill.sandbox_loader`

#### `SkillSandboxLoader(skill_service: SkillService, user_id: Optional[str] = None)`

负责将技能文件从数据库加载到沙箱文件系统。

**参数**：
- `skill_service`: SkillService 实例，用于数据库操作
- `user_id`: 用户ID，用于权限检查（默认 None）

**方法**：

- `async load_skill_to_sandbox(skill_id: uuid.UUID, backend: BackendProtocol, user_id: Optional[str] = None) -> bool`
  - 加载单个技能到沙箱
  - 返回 True 如果成功，False 如果失败

- `async load_skills_to_sandbox(skill_ids: list[uuid.UUID], backend: BackendProtocol, user_id: Optional[str] = None) -> dict[uuid.UUID, bool]`
  - 批量加载技能到沙箱
  - `backend`: BackendProtocol 实例
  - `user_id`: 用户ID，用于权限检查（可选）
  - 返回字典，映射 skill_id 到加载状态（True/False）
  - 注意：每次加载前会清理现有目录，确保文件是最新的

**文件组织**：
- 技能文件写入 `/workspace/skills/{skill_name}/`
- 保持原有的文件路径结构

### SkillService 方法

#### `get_skill_by_name(skill_name: str, current_user_id: Optional[str] = None) -> Optional[Skill]`

根据名称查找技能（不区分大小写）。

**参数：**
- `skill_name`: 技能名称
- `current_user_id`: 当前用户ID，用于权限检查

**返回：**
- `Skill` 对象，如果未找到或无权访问则返回 `None`

#### `format_skill_content(skill: Skill) -> str`

格式化技能内容为字符串。

**参数：**
- `skill`: Skill 对象（应包含 files 关系）

**返回：**
- 格式化后的技能内容字符串

## 未来增强

计划中的功能：

- [ ] 技能版本控制
- [ ] 技能使用分析
- [ ] 技能搜索和过滤
- [ ] 技能文件缓存优化
- [ ] 支持技能文件增量更新

## 相关文档

- [Skill 架构设计文档](../../skill/ARCHITECTURE.md) - 完整的架构设计和分层说明
- [LangChain Skills Pattern](https://docs.langchain.com/oss/python/langchain/multi-agent/skills-sql-assistant)
- [Progressive Disclosure](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Skill API 文档](../../../api/v1/skills.py)

## 支持

如有问题或建议，请：
1. 查看日志文件获取详细错误信息
2. 检查数据库连接和权限设置
3. 联系开发团队
