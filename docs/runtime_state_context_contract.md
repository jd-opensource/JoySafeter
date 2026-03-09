# Runtime State & Context Contract（权威定义）

> 目标：把“可视化配置 → Schema 编译 → 执行 → 中断/恢复 → 持久化”链路中，`state_fields` 与 `context` 的职责边界、合并规则、覆盖优先级、安全边界写成**唯一权威**说明，并能被测试锁定，避免返工。

---

## 1. 术语与对象

### 1.1 Graph Variables（DB 持久化）

图的持久化元数据位于 `AgentGraph.variables`（JSONB）。

当前仓库实践（见 `backend/app/services/graph_service.py`）：
- `variables.viewport`: 画布视口（前端 UI 状态）
- `variables.context`: **图级默认上下文**（Graph default context）
- `variables.state_fields`: **动态状态字段定义**（Dynamic state field definitions）
- 其他 key：允许扩展，但需要契约化（例如 `interrupts`、`tags` 等）

> 注意：GraphService.save_graph_state 会把前端传入的 `variables` **merge** 到 `graph.variables` 中（不做白名单过滤）。因此安全边界必须通过 API 层 / service 层 / schema 层约束。

### 1.2 Schema（编译输入）

标准 LangGraph 模式中，DB 模型会先被转换为 `GraphSchema`（见 `backend/app/core/graph/graph_schema.py`），再由 `GraphCompiler` 编译（见 `backend/app/core/graph/graph_compiler.py`）。

`GraphSchema` 关心两件与本契约相关的内容：
- `state_fields`: 从 `graph.variables.state_fields` 解析得到（`GraphSchema.from_db()`）
- `use_default_state`: 是否继承默认 `GraphState` 字段（当前实现默认为 `True`）

### 1.3 Runtime Input（运行时输入）

运行时输入通常来自 Chat API / 执行 API 对 `compiled_graph.ainvoke()` 的入参，典型包括：
- `messages`: 初始对话消息
- `context`: 请求级上下文（Request context，可覆盖部分默认值）
- 未来可扩展：`initial_state` / `thread_config` / `metadata` 等（需显式纳入本契约）

### 1.4 Runtime State（运行时状态）

运行时状态是 LangGraph 在执行过程中流转、合并、checkpoint 的对象：

- 默认状态类：`backend/app/core/graph/graph_state.py::GraphState`
- 动态状态类：由 `build_state_class(schema.state_fields, extend_default=...)` 生成（在 `GraphCompiler` 内构造）

---

## 2. `context` vs `state_fields`：职责边界

### 2.1 `context`（请求/图级上下文）

**定位**：给表达式、模板渲染、工具/节点执行提供“外部环境输入”。

典型内容：
- UI 提供的用户参数（例如 `user_type`, `retry_count`）
- 请求级追踪信息（`trace_id`）
- 租户/权限信息（`workspace_id`, `user_id`）——建议仅后端注入

默认约定：
- `context` 在 `GraphState.context` 中出现（见 `GraphState` 定义）
- `context` 的 key 允许由前端配置（图级默认），也允许由运行时请求注入（请求级覆盖）

**非目标**：
- 不建议把“需要被 checkpoint 且驱动流程的核心状态”长期放进 `context`（否则会造成“上下文即状态”的混乱）。

### 2.2 `state_fields`（可配置状态字段）

**定位**：可视化配置/业务流程需要的“结构化状态扩展”，并明确 reducer 行为（merge/add/replace 等），用于：
- 让工作流拥有**可预测**的状态结构
- 让 checkpoint 恢复后状态仍可重放
- 让并行/循环 reducer 有统一语义

典型内容：
- `todos`, `task_results` 这类“执行过程中会被不断累积/合并”的字段
- 图/业务特有的状态（例如 `score`, `items`, `selected_plan`）

约定：
- `state_fields` 定义影响“运行时 state class 的字段集合与 reducer”
- `state_fields` 不等价于 `context`：它描述的是“状态结构”，不是“注入数据来源”

---

## 3. 覆盖优先级（最核心规则）

### 3.1 合并的参与方

本项目当前可观察到的参与方：
1. 图级默认变量（DB）：`graph.variables.context`
2. 请求级上下文（API 入参）：`invoke_input.context`
3. checkpoint 恢复状态（如启用 checkpointer；当前实现存在 `Checkpointer` 概念，但具体恢复路径需以 Chat API 为准）
4. 系统注入（后端强制注入）：`user_id / workspace_id / trace_id / model params` 等

### 3.2 推荐的统一优先级（从低到高）

> 低优先级 = 作为默认值；高优先级 = 允许覆盖。

1. **图级默认 context**：`graph.variables.context`
2. **checkpoint 恢复的 state.context（如存在）**
3. **请求级 context**：`invoke_input.context`
4. **系统强制注入/覆盖**：例如 `context.user_id`、`context.workspace_id`、`context.trace_id`（安全必须最高优先级）

理由：
- 图级默认是“配置默认值”
- checkpoint 恢复代表“上一次运行的延续”（但不应该覆盖本次请求显式传入的参数）
- 请求级 context 是“本次运行的输入”
- 系统注入必须最后覆盖，避免前端/用户越权

### 3.3 `state_fields` 的覆盖规则

`state_fields` 影响的是“state class 定义”，而不是具体 state 值。

- state class 的字段集合以 `graph.variables.state_fields` 为准
- 运行时“具体 state 值”：
  - 如果字段属于 state（非 context）：由 checkpoint 恢复值优先，其次才是运行时 initial_state 的默认值（如有）
  - 如果字段属于 context：按 3.2 的优先级

---

## 4. 安全边界（必须明确禁止项）

由于 `GraphService.save_graph_state()` 对 `variables` 采取“全量 merge”，必须在 API/Service/Schema 层定义白名单策略，否则会出现：
- 前端可写入后端敏感字段
- 运行时可通过 context 覆盖系统参数

建议规则（需要实现/测试支撑）：

### 4.1 variables 白名单

允许前端写入的变量 key：
- `viewport`
- `context`
- `state_fields`

其余 key：
- 需要后端显式允许（否则拒绝或忽略）

### 4.2 context 写入限制

禁止前端/请求覆盖的 context key（建议后端保留前缀或名单）：
- `user_id`, `workspace_id`, `trace_id`
- `system_prompt`, `tools_whitelist`, `skills_whitelist`
- `model_name`, `api_key`, `base_url`

建议实现策略：
- 对系统保留字段采用统一前缀（例如 `_sys.*`），并在注入时写入 `_sys` 命名空间，避免与用户 context 冲突

---

## 5. 与现有实现的对照点（必须对齐的代码入口）

### 5.1 DB → Schema：state_fields

- `backend/app/core/graph/graph_schema.py::GraphSchema.from_db()`
  - `variables = getattr(graph, "variables", {}) or {}`
  - `state_field_defs = variables.get("state_fields", [])`

### 5.2 Schema → Runtime State Class

- `backend/app/core/graph/graph_compiler.py`
  - `build_state_class(self.schema.state_fields, extend_default=self.schema.use_default_state)`

### 5.3 Save/Load：variables merge 行为（风险点）

- `backend/app/services/graph_service.py::GraphService._save_graph_state_internal()`
  - `for key, value in variables.items(): graph_variables[key] = value`

---

## 6. 测试契约（验收标准）

本契约必须通过测试锁定，至少包含：

1. **Graph variables 合并规则**
- 保存时：viewport 不丢失；variables 合并不会意外覆盖非目标字段（若启用白名单）
- 加载时：variables 原样返回，context/state_fields 可见

2. **state_fields 解析与动态 state class 构造**
- 给定 `graph.variables.state_fields`，GraphSchema 能解析出同数量字段
- GraphCompiler 能成功构建 dynamic state class（字段存在）

3. **context 优先级**
- 图级默认 context + 请求级 context 合并后，关键 key 的值符合“请求覆盖默认”
- 若存在系统注入字段，则系统注入最终覆盖

---

## 7. 文档引用约束（避免多头定义）

从现在起：
- `docs/GRAPH_BUILDER_ARCHITECTURE.md` 附录 B（context vs state_fields）应改为引用本文件，不再在附录中重复定义。
- 任何新文档若涉及 `context/state_fields`，必须引用本文件为准。