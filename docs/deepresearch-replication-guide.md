# DeepResearch 复刻指南（快速参考）

> **完整文档请参考**：[DeepResearch 完整复刻指南](./deepresearch-complete-guide.md)

本文档是 DeepResearch 工作流的快速参考指南。详细配置说明、工作流结构、节点配置和架构差异说明请参考完整指南。

## 能力验证结果

### 1. 复杂条件表达式支持 ✅

**前端支持**：
- `router_node` 使用 `ConditionExprField`，支持变量自动补全
- 可以通过 `context.get('current_plan')` 访问复杂对象
- 支持嵌套对象访问（如 `context.get('current_plan', {}).get('step_type')`）

**后端支持**：
- `RouterNodeExecutor._evaluate_rule` 中，`eval_context` 包含 `context` 字典
- 支持通过 `context.get('key')` 访问复杂对象
- 对于嵌套对象，如果存储为字典，使用 `context.get('current_plan', {}).get('step_type')`
- 如果存储为对象，可以使用点号访问（需要确保对象在 eval 上下文中可用）

**示例表达式**：
```python
# 访问嵌套对象（字典形式）
context.get('current_plan', {}).get('step_type') == 'research'

# 检查计划是否完成
all(step.get('execution_res') for step in context.get('current_plan', {}).get('steps', []))

# 检查是否有未完成的步骤
any(not step.get('execution_res') for step in context.get('current_plan', {}).get('steps', []))
```

### 2. Loop Back 边可视化编辑 ✅

**前端支持**：
- `onConnect` 自动检测并设置 `loop_back` 类型
- `LoopBackEdge` 组件支持可视化编辑（可拖拽控制点）
- 支持从循环体回到路由节点的场景
- 自动识别循环结构（通过位置判断或自循环）

**使用方式**：
1. 从 `loop_condition_node` 创建 `continue_loop` 边
2. 如果目标节点在源节点左侧，自动识别为 `loop_back`
3. 可以在边的属性面板中手动设置 `edge_type` 为 `loop_back`

### 3. 状态上下文访问 ✅

**验证结果**：
- `GraphState.context` 是 `Dict[str, Any]` 类型，可以存储任意复杂对象
- 节点执行器可以通过 `state.get("context", {})` 访问上下文
- 支持在条件表达式中访问 `context` 中的复杂对象
- 支持在节点配置中使用 `context.get('key')` 进行变量替换

**注意事项**：
- 如果 `context` 中存储的是字典，使用 `.get()` 方法访问
- 如果存储的是对象，需要确保对象在 eval 上下文中可用
- 建议将复杂对象序列化为字典存储，便于条件表达式访问

## DeepResearch 工作流配置

### 节点映射表

| Deer-Flow 节点 | 当前项目节点类型 | 配置要点 |
|---------------|----------------|---------|
| `coordinator` | `agent` | 配置 systemPrompt 处理用户输入和澄清 |
| `background_investigator` | `agent` + `tool_node` | 使用 web_search 工具 |
| `planner` | `agent` | 配置 systemPrompt 生成计划，使用条件边路由 |
| `research_team` | `router_node` | 根据计划状态路由到 researcher/coder |
| `researcher` | `agent` + `tool_node` | 配置 web_search、crawl 工具 |
| `coder` | `agent` + `tool_node` | 配置 python_repl 工具 |
| `reporter` | `agent` | 配置 systemPrompt 生成报告 |
| `human_feedback` | `human_input` | 配置 interrupt_before |

### 工作流结构

```
START
  ↓
coordinator (agent)
  ↓
background_investigator (agent + tool_node) [可选]
  ↓
planner (agent)
  ├─→ human_feedback (human_input) [条件边: 计划未通过]
  │     ↓
  │   planner (循环)
  └─→ research_team (router_node) [条件边: 计划通过]
        ├─→ researcher (agent + tool_node) [条件边: step_type == 'research']
        │     ↓
        │   loop_condition_node (检查是否完成)
        │     ├─ continue_loop (loop_back) → research_team
        │     └─ exit_loop → reporter
        └─→ coder (agent + tool_node) [条件边: step_type == 'processing']
              ↓
            loop_condition_node (检查是否完成)
              ├─ continue_loop (loop_back) → research_team
              └─ exit_loop → reporter
```

### 关键配置示例

#### 1. research_team (router_node)

**路由规则**：
```json
{
  "routes": [
    {
      "id": "route_research",
      "condition": "context.get('current_plan', {}).get('steps', []) and any(not step.get('execution_res') for step in context.get('current_plan', {}).get('steps', [])) and next((step for step in context.get('current_plan', {}).get('steps', []) if not step.get('execution_res')), {}).get('step_type') == 'research'",
      "targetEdgeKey": "researcher",
      "label": "Route to Researcher",
      "priority": 0
    },
    {
      "id": "route_coder",
      "condition": "context.get('current_plan', {}).get('steps', []) and any(not step.get('execution_res') for step in context.get('current_plan', {}).get('steps', [])) and next((step for step in context.get('current_plan', {}).get('steps', []) if not step.get('execution_res')), {}).get('step_type') == 'processing'",
      "targetEdgeKey": "coder",
      "label": "Route to Coder",
      "priority": 1
    },
    {
      "id": "route_planner",
      "condition": "True",
      "targetEdgeKey": "planner",
      "label": "All steps completed, return to planner",
      "priority": 2
    }
  ],
  "defaultRoute": "planner"
}
```

**简化版本**（如果计划存储在 context 中）：
```json
{
  "routes": [
    {
      "id": "route_research",
      "condition": "context.get('current_step_type') == 'research'",
      "targetEdgeKey": "researcher",
      "label": "Route to Researcher",
      "priority": 0
    },
    {
      "id": "route_coder",
      "condition": "context.get('current_step_type') == 'processing'",
      "targetEdgeKey": "coder",
      "label": "Route to Coder",
      "priority": 1
    },
    {
      "id": "route_planner",
      "condition": "True",
      "targetEdgeKey": "planner",
      "label": "All steps completed",
      "priority": 2
    }
  ],
  "defaultRoute": "planner"
}
```

#### 2. loop_condition_node (检查是否完成)

**配置**：
```json
{
  "conditionType": "while",
  "condition": "context.get('current_plan', {}).get('steps', []) and any(not step.get('execution_res') for step in context.get('current_plan', {}).get('steps', []))",
  "maxIterations": 20
}
```

**边配置**：
- `continue_loop` → `research_team` (loop_back 类型)
- `exit_loop` → `reporter`

#### 3. planner (agent)

**systemPrompt 示例**：
```
You are a research planner. Your task is to create a detailed research plan based on the user's query.

The plan should include:
1. A clear title
2. A description of the research goal
3. A list of steps, each with:
   - title: Brief step title
   - description: What to do in this step
   - step_type: Either "research" or "processing"
   - need_search: Boolean indicating if web search is needed

Output format (JSON):
{
  "title": "Research Title",
  "thought": "Research description",
  "steps": [
    {
      "title": "Step 1",
      "description": "Step description",
      "step_type": "research",
      "need_search": true
    }
  ],
  "has_enough_context": false
}

Store the plan in context.current_plan as a dictionary.
```

**条件边配置**：
- `human_feedback` (route_key: "needs_review") - 当 `has_enough_context == false`
- `research_team` (route_key: "approved") - 当 `has_enough_context == true`

#### 4. researcher (agent + tool_node)

**systemPrompt**：
```
You are a researcher. Your task is to conduct research on the current step.

Use the web_search tool to find relevant information.
Use the crawl tool to extract content from web pages.

After completing the research, store the findings in context.current_plan.steps[<current_step_index>].execution_res.
```

**工具配置**：
- `web_search` (tool_node)
- `crawl` (tool_node)

#### 5. coder (agent + tool_node)

**systemPrompt**：
```
You are a code analyst. Your task is to analyze code or data for the current step.

Use the python_repl tool to execute Python code for analysis.

After completing the analysis, store the results in context.current_plan.steps[<current_step_index>].execution_res.
```

**工具配置**：
- `python_repl` (tool_node)

#### 6. reporter (agent)

**systemPrompt**：
```
You are a report writer. Your task is to synthesize all research findings into a comprehensive report.

Use the information from context.current_plan.steps[].execution_res to create the final report.

The report should include:
1. Executive Summary
2. Key Findings
3. Detailed Analysis
4. Conclusions

Output the final report as markdown.
```

## 实施步骤

1. **创建节点**：
   - 按照节点映射表创建所有节点
   - 配置每个节点的 systemPrompt 和工具

2. **配置路由**：
   - 为 `planner` 节点配置条件边（human_feedback / research_team）
   - 为 `research_team` 节点配置路由规则（researcher / coder / planner）

3. **配置循环**：
   - 在 `researcher` 和 `coder` 后添加 `loop_condition_node`
   - 配置 `continue_loop` 边（loop_back 类型）回到 `research_team`
   - 配置 `exit_loop` 边到 `reporter`

4. **配置中断**：
   - 为 `human_feedback` 节点配置 `interrupt_before: true`

5. **测试验证**：
   - 测试完整工作流执行
   - 验证循环逻辑
   - 验证中断和恢复功能

## 注意事项

1. **状态管理**：
   - 确保计划对象以字典形式存储在 `context.current_plan`
   - 步骤执行结果存储在 `context.current_plan.steps[].execution_res`

2. **条件表达式**：
   - 使用 `context.get('key', {})` 安全访问嵌套对象
   - 避免直接访问可能不存在的键

3. **循环控制**：
   - 设置合理的 `maxIterations` 防止无限循环
   - 确保循环条件能正确判断完成状态

4. **工具配置**：
   - 确保所需工具已在工具注册表中注册
   - 配置正确的工具输入映射

## 参考资源

- [Graph Builder Architecture](../docs/GRAPH_BUILDER_ARCHITECTURE.md)
- [Loop Back Edge Usage](../docs/loop-back-edge-usage.md)
- [Node Type Reference](../docs/GRAPH_BUILDER_ARCHITECTURE.md#5-节点类型完整参考)
