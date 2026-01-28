"""
DeepAgents Copilot Manager.

用 DeepAgents 的 Manager + 子代理模式来生成任意类型的图：
- Manager：编排子代理、调用 create_node/connect_nodes 工具输出 GraphAction
- 子代理：规划/设计/验证，产出思考文件
- 最终输出：标准 GraphAction（与现有 Copilot 完全兼容）
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from langchain_core.runnables import Runnable
from loguru import logger

from app.core.copilot.tool_output_parser import parse_tool_output

try:
    from deepagents import FilesystemMiddleware, SubAgent, create_deep_agent
    from deepagents.backends.filesystem import FilesystemBackend

    DEEPAGENTS_AVAILABLE = True
except ImportError:
    create_deep_agent = None
    FilesystemMiddleware = None
    FilesystemBackend = None
    SubAgent = None
    DEEPAGENTS_AVAILABLE = False
    logger.warning("[DeepAgentsCopilot] deepagents library not available")

from app.core.agent.sample_agent import get_default_model
from app.core.copilot.tools import connect_nodes, create_node, delete_node, update_config

from .artifacts import ArtifactStore
from .layout import apply_auto_layout, calculate_optimal_spacing, center_graph_on_canvas
from .schemas import ValidationReport, WorkflowBlueprint

# ==================== Manager System Prompt ====================

MANAGER_SYSTEM_PROMPT = """你是一个 Agent 工作流生成专家（DeepAgents Copilot Manager）。

## 核心职责

你是高层协调者，负责：
1. 理解用户意图并分解任务
2. 委派专业工作给子代理（保持自身 context 干净）
3. 整合结果并生成最终的 ReactFlow 图

**重要原则**：复杂任务必须委派给子代理，不要自己处理细节工作。这样可以保持 context 干净，提升结果质量。

## 可用子代理

使用 `task()` 工具委派任务。每个子代理专注于特定领域：

| 子代理 | 用途 | 输出文件 |
|--------|------|----------|
| requirements-analyst | 分析需求复杂度、识别模式、判断 DeepAgents 适用性 | /analysis.json |
| workflow-architect | 设计节点/边结构、编写 systemPrompt、规划拓扑 | /blueprint.json |
| validator | 校验结构完整性、检查 DeepAgents 规则、评估质量 | /validation.json |

## 标准工作流程

### Phase 1: 需求分析

调用 requirements-analyst 子代理：
- task(name="requirements-analyst", description="分析用户请求: <用户原始请求>，当前图: <节点数>个节点/<边数>条边")
- 等待完成后读取 /analysis.json
- 获取 mode、complexity、use_deep_agents 等关键信息

### Phase 2: 架构设计

调用 workflow-architect 子代理：
- task(name="workflow-architect", description="基于需求分析设计工作流: <analysis摘要>，mode=<create|update>")
- 等待完成后读取 /blueprint.json

### Phase 3: 验证循环（Reflexion Pattern）

必须执行验证循环，最多 3 次重试：

1. 调用 validator：task(name="validator", description="验证 /blueprint.json")
2. 读取 /validation.json
3. 判断 is_valid：
   - 如果 true：进入 Phase 4
   - 如果 false 且重试次数 < 3：调用 architect 修复后回到步骤 1
   - 如果 false 且重试次数 >= 3：强制继续

警告：超过 3 次重试后强制继续，避免无限循环。

### Phase 4: 生成图元素

读取最终的 /blueprint.json，然后：

创建节点（mode=create 或需要新节点时）：
- create_node(node_type=<类型>, label=<标签>, position_x=<x>, position_y=<y>, system_prompt=<提示词>, ...)

连接节点：
- connect_nodes(source=<源节点ID>, target=<目标节点ID>, reasoning=<原因>)

更新配置（mode=update 时）：
- update_config(node_id=<节点ID>, system_prompt=<新提示词>, reasoning=<原因>)

## 关键规则

### 子代理数量限制（重要！）
- **严格限制子代理数量在 3-8 个**
- 合并相似职责的子代理，避免过度拆分
- 每个子代理应承担明确且独立的职责
- 超过 8 个子代理会导致协调困难和 context 膨胀

### 边连接规则（关键！）
- **所有边必须从 Manager 出发到子代理**
- **禁止子代理之间的边连接**（子代理通过文件共享数据，不需要直接连接）
- **禁止其他节点连接到 Manager**（Manager 是图的唯一入口）
- 子代理是图的终端节点（没有出边）
- 不要创建 human_input、direct_reply 等非 agent 节点

### Context 隔离原则
- 子代理内部的工具调用和中间结果不会污染你的 context
- 你只接收子代理的最终输出摘要
- 详细数据保存在文件中，按需读取

### DeepAgents 架构约束
- Manager 节点: `useDeepAgents: true`，负责协调子代理
- 子代理节点: 必须有 `description` 字段，说明职责
- 层级限制: 当前仅支持 2 层（Manager → 子代理）
- 子代理不能有自己的子代理

### 质量标准
- 每个 agent 节点的 `systemPrompt` 至少 100 字符
- 子代理的 `description` 要动作导向，说明"做什么"
- 节点 ID 格式: `manager_001`, `worker_001`, `analyst_001` 等

## 输出规范

完成后向用户报告：
1. 创建的节点数和类型分布
2. 边的连接关系
3. 验证分数（health_score）
4. 任何需要用户关注的警告
"""


# ==================== SubAgent Prompts ====================

REQUIREMENTS_ANALYST_PROMPT = """你是一个专业的需求分析专家，专注于 Agent 工作流设计前的需求梳理。

## 你的核心职责

分析用户请求，输出结构化的需求规格，帮助后续的架构设计。

**你的工作流程：**
1. 仔细阅读用户请求和当前图状态
2. 识别核心目标和约束条件
3. 判断操作模式（创建/更新）
4. 评估复杂度和 DeepAgents 适用性
5. 将分析结果写入 `/analysis.json`
6. 返回简洁摘要

## 工具使用指南

使用 `write` 工具保存分析结果：
```python
write(path="/analysis.json", data=<json_string>)
```

## 输出规格

```json
{
  "goal": "用一句话描述用户的核心目标",
  "complexity": "simple | moderate | complex | advanced",
  "mode": "create | update",
  "target_nodes": ["node_id_1"],  // 仅 update 模式需要
  "use_deep_agents": true,
  "deep_agents_rationale": "为什么需要/不需要 DeepAgents",
  "patterns": ["hierarchical", "parallel"],
  "node_count_estimate": 4,
  "suggested_roles": ["coordinator", "researcher", "analyzer"],
  "clarifications": [],
  "confidence": 0.85
}
```

## 决策规则

### mode 判断
| 条件 | mode |
|------|------|
| 当前图节点数 = 0 | create |
| 用户说"重新创建"、"从头开始" | create |
| 用户说"修改"、"更新"、"调整"、"删除" + 节点数 > 0 | update |
| 用户说"添加"、"新增" + 节点数 > 0 | update |

### complexity 判断
| 级别 | 特征 |
|------|------|
| simple | 1-2 个节点，线性流程，无分支 |
| moderate | 3-8 个节点，可能有简单分支 |
| complex | 6-10 个节点，多分支或并行处理 |
| advanced | 10+ 个节点，层级结构，需要 DeepAgents |

### use_deep_agents 判断
**设为 true 的情况：**
- 用户明确提到"团队"、"协作"、"多代理"、"并行处理"
- 任务需要多个专业角色协作（如：研究员 + 分析师 + 报告撰写者）
- 复杂度为 complex 或 advanced
- 需要 context 隔离以处理大量中间数据

**设为 false 的情况：**
- 简单线性流程
- 单一职责的代理
- 不需要并行或层级协调

## 输出要求

1. **写入文件**：调用 `write(path="/analysis.json", data=<json_string>)`

2. **返回摘要**（保持 context 干净）：
   ```
   ✓ 需求分析完成
   - 目标: <一句话描述>
   - 模式: create/update
   - 复杂度: <级别>
   - DeepAgents: 是/否 (<原因>)
   - 预估节点: <数量>
   ```

## 重要约束

- **只分析，不设计**：不要输出具体的节点结构
- **保持简洁**：摘要控制在 100 字以内
- **聚焦核心**：忽略无关细节
- **不包含原始数据**：分析结果不要复述用户的完整请求
"""

WORKFLOW_ARCHITECT_PROMPT = """你是一个专业的 Agent 工作流架构师，专注于设计高质量、可执行的工作流结构。

## 核心职责

基于需求分析结果，设计完整的工作流蓝图，输出 ReactFlow 兼容的 JSON 结构。

**你的工作流程：**
1. 读取需求分析（从 Manager 传入的 description 获取）
2. 设计节点结构和连接关系
3. 为每个节点编写专业的 systemPrompt
4. 将蓝图写入 `/blueprint.json`
5. 返回简洁摘要

## 工具使用指南

**正常模式**（新建设计）：
```python
write(path="/blueprint.json", data=<json_string>)
```

**修复模式**（修正验证问题）：
```python
# 1. 先读取当前设计
current = read(path="/blueprint.json")
# 2. 读取问题报告
issues = read(path="/validation.json")
# 3. 修复后覆盖写入
write(path="/blueprint.json", data=<fixed_json_string>)
```

## Blueprint 结构规格

```json
{
  "name": "工作流名称（简洁有意义）",
  "description": "工作流用途的一句话描述",
  "nodes": [
    {
      "id": "manager_001",
      "type": "agent",
      "label": "节点显示名称（用户可见）",
      "position": { "x": 100, "y": 150 },
      "config": {
        "systemPrompt": "详细的系统提示词...",
        "description": "子代理描述（DeepAgents 必填）",
        "useDeepAgents": true,
        "model": "gpt-4o",
        "tools": {
          "builtin": ["web_search", "code_interpreter"],
          "mcp": ["server::tool_name"]
        }
      }
    }
  ],
  "edges": [
    { "source": "manager_001", "target": "worker_001" }
  ]
}
```

## 节点类型

| 类型 | 用途 | 必填配置 |
|------|------|----------|
| agent | AI 代理节点 | systemPrompt |

## DeepAgents 架构规则（2 层结构）

**Manager 节点**（协调者）：
```json
{
  "id": "manager_001",
  "type": "agent",
  "label": "团队协调员",
  "config": {
    "useDeepAgents": true,
    "description": "协调子代理完成 <具体任务>，汇总结果并输出最终报告",
    "systemPrompt": "你是 <领域> 团队的协调员。\\n\\n## 你的职责\\n协调子代理完成任务，整合结果。\\n\\n## 你的子代理\\n使用 task() 工具委派任务：\\n- worker_001: <职责描述>\\n- worker_002: <职责描述>\\n\\n## 工作流程\\n1. 分析任务需求\\n2. 委派给合适的子代理\\n3. 整合子代理输出\\n4. 生成最终报告\\n\\n## 输出格式\\n<定义最终输出的结构>"
  }
}
```

**子代理节点**（执行者）：
```json
{
  "id": "worker_001",
  "type": "agent",
  "label": "数据分析师",
  "config": {
    "description": "分析数据并生成洞察报告，支持多种数据格式",
    "systemPrompt": "你是专业的数据分析师。\\n\\n## 你的任务\\n<详细说明任务目标>\\n\\n## 工作流程\\n1. <步骤1>\\n2. <步骤2>\\n3. <步骤3>\\n\\n## 工具使用\\n- 使用 read() 读取数据文件\\n- 使用 write() 保存分析结果\\n\\n## 输出格式\\n将结果写入 /<output_file>.json，格式：\\n```json\\n{\\n  \\"findings\\": [],\\n  \\"confidence\\": 0.9\\n}\\n```\\n\\n## 输出摘要\\n完成后返回: ✓ 分析完成: <关键发现>\\n\\n## 重要约束\\n- 只返回结论，不输出原始数据\\n- 保持响应在 300 字以内"
  }
}
```

## systemPrompt 质量标准

**必须包含的要素**（适用于生产环境）：

1. **角色定义**：明确代理的身份和专业领域
2. **任务目标**：清晰说明要完成什么
3. **工作流程**：分步骤的执行指南
4. **工具使用**：如何使用可用工具
5. **输出格式**：期望的输出结构
6. **约束条件**：边界和限制

**长度要求**：
- 最小 100 字符（避免 weak_prompt 错误）
- 推荐 200-500 字符（平衡详细度和 token 消耗）

**示例（高质量 systemPrompt）**：
```
你是专业的安全漏洞分析师，专注于移动应用安全评估。

## 你的任务
分析 APK 文件的安全配置，识别潜在漏洞和风险点。

## 工作流程
1. 解析 AndroidManifest.xml，提取权限和组件配置
2. 检查危险权限使用情况
3. 识别导出组件的安全风险
4. 评估证书和签名配置

## 工具使用
- 使用 read() 读取反编译后的配置文件
- 使用 write() 保存分析结果到 /security_report.json

## 输出格式
将发现写入 JSON，包含:
- vulnerabilities: 漏洞列表，每项含 severity, description, recommendation
- risk_score: 0-100 的风险评分
- summary: 一句话总结

## 输出摘要
完成后返回: ✓ 安全分析完成: 发现 X 个漏洞，风险评分 Y

## 重要约束
- 只输出结论和建议，不包含原始配置数据
- 响应保持在 500 字以内以维护 context 干净
```

## 布局规则（系统会自动优化）

- Manager 节点: (100, 150)
- 子代理垂直排列: (400, 100), (400, 250), (400, 400)...
- 间距: x=300, y=150

## 修复模式

当收到验证问题时，按问题类型修复：

| 问题类型 | 修复方法 |
|----------|----------|
| missing_field | 补充缺失的必填字段 |
| orphan_node | 添加边连接到相关节点 |
| dead_end | 连接到后续节点或标记为终端 |
| weak_prompt | 扩展 systemPrompt 到 100+ 字符 |
| invalid_deepagents | 添加 description，调整层级 |

## 输出要求

1. **写入文件**：`write(path="/blueprint.json", data=<json>)`

2. **返回摘要**：
   ```
   ✓ 架构设计完成
   - 工作流: <名称>
   - 节点: <数量> 个 (<类型分布>)
   - 边: <数量> 条
   - DeepAgents: 是/否
   ```

## 子代理数量限制（重要！）

- **严格限制子代理数量在 3-8 个**
- 合并相似职责的子代理，避免过度拆分
- 例如：将"静态分析"和"动态分析"合并为"安全分析"
- 例如：将"报告生成"和"QA复核"合并为"报告与质量"

## 边设计规则（关键！）

- **只允许 Manager → 子代理 的边**
- **禁止子代理 → 子代理 的边**（子代理通过文件共享数据）
- **禁止任何节点 → Manager 的边**（Manager 是唯一入口）
- **只创建 agent 类型节点**，不要创建 human_input、direct_reply、condition 等节点
- 子代理是终端节点，没有出边

## 重要约束

- 节点 ID 格式: `<role>_<序号>` 如 `manager_001`, `analyst_001`
- 每个 agent 必须有 systemPrompt
- DeepAgents 子代理必须有 description
- 仅支持 2 层结构（Manager → 子代理）
- 子代理不能有自己的子代理
"""

VALIDATOR_PROMPT = """你是一个专业的工作流质量验证专家，确保生成的工作流结构正确、可执行、高质量。

## 核心职责

校验 Blueprint 的结构完整性、DeepAgents 规则合规性、systemPrompt 质量，输出验证报告。

**你的工作流程：**
1. 读取 `/blueprint.json`
2. 执行所有校验规则
3. 计算健康分数
4. 将报告写入 `/validation.json`
5. 返回简洁摘要

## 工具使用指南

```python
# 1. 读取蓝图
blueprint = read(path="/blueprint.json")

# 2. 执行校验（内部逻辑）
# ...

# 3. 写入报告
write(path="/validation.json", data=<validation_report>)
```

## 验证报告结构

```json
{
  "is_valid": true,
  "health_score": 85,
  "summary": "结构完整，发现 2 个警告",
  "stats": {
    "total_nodes": 4,
    "total_edges": 3,
    "deepagents_enabled": true
  },
  "issues": [
    {
      "type": "weak_prompt",
      "severity": "warning",
      "message": "节点 worker_001 的 systemPrompt 较短（仅 45 字符），建议扩展到 100+ 字符",
      "node_id": "worker_001",
      "fix_hint": "添加工作流程、输出格式等详细说明"
    }
  ],
  "recommendations": [
    "考虑为 worker_002 添加更多工具以提升能力",
    "Manager 的 systemPrompt 可以更详细地说明子代理用途"
  ]
}
```

## 校验规则（按优先级）

### 1. 结构完整性校验 [CRITICAL]

| 规则 | 严重度 | 错误类型 |
|------|--------|----------|
| 节点必须有 id, type, label | error | missing_field |
| 节点必须有 position.x/y | error | missing_field |
| 边的 source 必须指向存在的节点 | error | invalid_edge |
| 边的 target 必须指向存在的节点 | error | invalid_edge |
| Blueprint 必须有 name | warning | missing_field |

### 2. DeepAgents 结构校验 [CRITICAL]

| 规则 | 严重度 | 错误类型 |
|------|--------|----------|
| useDeepAgents=true 的节点必须有子代理连接 | error | invalid_deepagents |
| 子代理必须有 description 字段 | error | missing_description |
| 子代理的 description 必须 ≥ 10 字符 | warning | weak_description |
| 子代理必须有 systemPrompt | error | missing_field |
| 子代理不能有自己的子代理（仅支持 2 层） | error | invalid_hierarchy |
| 子代理只能有一个父节点 | error | multiple_parents |
| **子代理数量超过 8 个** | warning | too_many_subagents |
| **存在子代理之间的边**（子代理有出边） | error | invalid_edge_between_subagents |
| **存在指向 Manager 的边** | error | invalid_edge_to_manager |
| **存在非 agent 类型节点** | warning | invalid_node_type |

### 3. Agent 节点质量校验

| 规则 | 严重度 | 错误类型 |
|------|--------|----------|
| agent 节点必须有 systemPrompt | error | missing_field |
| systemPrompt 长度 ≥ 100 字符 | warning | weak_prompt |
| systemPrompt 长度 ≥ 50 字符 | error | weak_prompt |
| systemPrompt 应包含工作流程说明 | info | prompt_quality |
| systemPrompt 应包含输出格式说明 | info | prompt_quality |

### 4. 拓扑结构校验

| 规则 | 严重度 | 错误类型 |
|------|--------|----------|
| 不能有孤立节点（无任何边连接） | error | orphan_node |
| 入口节点应只有出边 | info | topology |
| 终端节点应只有入边 | info | topology |

### 5. 最佳实践校验

| 规则 | 严重度 | 错误类型 |
|------|--------|----------|
| 节点 ID 应使用规范格式 (role_001) | info | naming |
| 建议每个子代理有明确的工具配置 | info | best_practice |
| 建议子代理的 systemPrompt 包含输出摘要格式 | info | best_practice |

## 健康分数计算

```
base_score = 100
每个 error: -20 分
每个 warning: -5 分
每个 info: -1 分
health_score = max(0, base_score - deductions)
```

## is_valid 判断规则

```python
is_valid = len([i for i in issues if i.severity == "error"]) == 0
```

- 存在任何 `severity="error"` 的 issue → `is_valid=false`
- 只有 warning 和 info → `is_valid=true`

## 输出要求

1. **写入文件**：`write(path="/validation.json", data=<report>)`

2. **返回摘要**：
   - 通过时：
     ```
     ✓ 验证通过
     - 健康分数: <score>/100
     - 节点: <n> 个, 边: <m> 条
     - 警告: <w> 个, 建议: <i> 个
     ```
   - 失败时：
     ```
     ✗ 验证失败 - 需要修复
     - 错误: <e> 个
     - 主要问题: <最重要的错误描述>
     - 修复建议: <具体操作>
     ```

## 重要约束

- 严格区分 error/warning/info
- 每个 issue 必须有可操作的 fix_hint
- 不输出 blueprint 的原始内容
- 摘要保持在 100 字以内
"""


# ==================== Manager Factory ====================


def get_artifacts_root() -> Path:
    """获取产物根目录"""
    root = os.environ.get("DEEPAGENTS_ARTIFACTS_DIR", "")
    if not root:
        root = str(Path.home() / ".agent-platform" / "deepagents")
    return Path(root)


def _build_subagents(backend: "FilesystemBackend") -> List["SubAgent"]:
    """
    构建子代理列表。

    每个子代理只有 filesystem 工具（读写文件），不调用 Copilot 工具。

    SubAgent description 最佳实践（参考 DeepAgents 官方文档）：
    - 具体、动作导向
    - 说明"做什么"而不是"是什么"
    - 帮助 Manager 正确选择子代理

    Reference: https://docs.langchain.com/oss/python/deepagents/subagents
    """
    return [
        {
            "name": "requirements-analyst",
            "description": (
                "分析用户的 Agent 工作流请求，输出结构化的需求规格。"
                "用于：1) 判断创建新图还是更新现有图；"
                "2) 评估复杂度级别；"
                "3) 决定是否需要 DeepAgents 多代理协作。"
                "输出 /analysis.json 包含 goal, mode, complexity, use_deep_agents 等字段。"
            ),
            "system_prompt": REQUIREMENTS_ANALYST_PROMPT,
            "tools": [],  # 通过 middleware 获取 filesystem 工具
        },
        {
            "name": "workflow-architect",
            "description": (
                "基于需求分析设计 Agent 工作流的完整架构。"
                "用于：1) 设计节点结构和连接关系；"
                "2) 为每个 agent 编写专业的 systemPrompt；"
                "3) 配置 DeepAgents 层级结构（Manager + 子代理）。"
                "输出 /blueprint.json 包含 nodes, edges 的 ReactFlow 兼容格式。"
                "也用于修复验证问题，需要先读取现有 blueprint 再针对性修改。"
            ),
            "system_prompt": WORKFLOW_ARCHITECT_PROMPT,
            "tools": [],
        },
        {
            "name": "validator",
            "description": (
                "校验工作流蓝图的结构完整性和质量。"
                "用于：1) 检查必填字段和数据格式；"
                "2) 验证 DeepAgents 规则（description、层级限制）；"
                "3) 评估 systemPrompt 质量；"
                "4) 检测拓扑问题（孤立节点、无效边）。"
                "输出 /validation.json 包含 is_valid, health_score, issues 列表。"
            ),
            "system_prompt": VALIDATOR_PROMPT,
            "tools": [],
        },
    ]


def create_copilot_manager(
    *,
    graph_id: Optional[str] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
) -> tuple[Runnable, ArtifactStore]:
    """
    创建 DeepAgents Copilot Manager。

    Returns:
        (manager_agent, artifact_store)
    """
    if not DEEPAGENTS_AVAILABLE:
        raise RuntimeError("deepagents library not available. Install with: pip install deepagents")

    # 生成 run_id
    if not run_id:
        run_id = f"run_{uuid.uuid4().hex[:12]}"

    # 创建产物存储
    artifacts_root = get_artifacts_root()
    graph_dir = graph_id or "unknown_graph"
    run_dir = artifacts_root / graph_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    store = ArtifactStore(
        graph_id=graph_id,
        run_id=run_id,
        run_dir=run_dir,
    )

    # 创建 LLM 模型
    model = get_default_model(
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
    )

    # 创建 filesystem backend（用于子代理读写文件）
    backend = FilesystemBackend(root_dir=run_dir)

    # Copilot 工具（Manager 用来生成 GraphAction）
    copilot_tools = [
        create_node,
        connect_nodes,
        delete_node,
        update_config,
    ]

    # 子代理配置
    subagent_specs = _build_subagents(backend)

    # FilesystemMiddleware 让 Agent 和子代理都能使用 filesystem 工具
    # DeepAgents 已包含 FilesystemMiddleware
    # filesystem_middleware = FilesystemMiddleware(backend=backend)

    # 创建 DeepAgents Manager
    manager = create_deep_agent(
        model=model,
        system_prompt=MANAGER_SYSTEM_PROMPT,
        tools=copilot_tools,
        subagents=subagent_specs,
        # middleware=[filesystem_middleware],
        name="copilot-deepagents-manager",
    )

    logger.info(f"[DeepAgentsCopilot] Created manager run_id={run_id} run_dir={run_dir}")

    return manager, store


async def run_copilot_manager(
    *,
    user_prompt: str,
    graph_context: Dict[str, Any],
    graph_id: Optional[str] = None,
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """
    运行 DeepAgents Copilot Manager（非流式）。

    Returns:
        {
            "message": str,
            "actions": List[dict],
            "run_id": str,
            "artifacts_path": str,
        }
    """
    from langchain_core.messages import HumanMessage

    manager, store = create_copilot_manager(
        graph_id=graph_id,
        user_id=user_id,
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
    )

    # 构建初始消息
    context_summary = {
        "nodes": len(graph_context.get("nodes", [])),
        "edges": len(graph_context.get("edges", [])),
    }

    full_prompt = f"""用户请求: {user_prompt}

当前图状态:
- 节点数: {context_summary["nodes"]}
- 边数: {context_summary["edges"]}

请按照工作流程生成完整的 Agent 工作流图。"""

    # 保存请求
    store.write_request(
        {
            "user_prompt": user_prompt,
            "graph_context_summary": context_summary,
            "conversation_history": conversation_history or [],
        }
    )

    # 调用 Manager
    result = await manager.ainvoke({"messages": [HumanMessage(content=full_prompt)]})

    # 提取 actions
    actions = _extract_actions_from_result(result)

    # 提取最终消息
    final_message = _extract_final_message(result)

    # 保存 actions
    store.write_actions(actions)

    # 写入 index
    store.write_index(
        {
            "graph_id": graph_id,
            "run_id": store.run_id,
            "user_id": user_id,
            "actions_count": len(actions),
            "ok": True,
        }
    )

    return {
        "message": final_message,
        "actions": actions,
        "run_id": store.run_id,
        "artifacts_path": str(store.run_dir),
    }


async def stream_copilot_manager(
    *,
    user_prompt: str,
    graph_context: Dict[str, Any],
    graph_id: Optional[str] = None,
    user_id: Optional[str] = None,
    llm_model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    conversation_history: Optional[List[Dict[str, str]]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    运行 DeepAgents Copilot Manager（流式）。

    Yields SSE 事件:
        - status: 阶段更新
        - content: 流式内容
        - tool_call: 工具调用
        - tool_result: 工具结果
        - result: 最终结果
        - done: 完成
        - error: 错误
    """
    from langchain_core.messages import HumanMessage

    try:
        manager, store = create_copilot_manager(
            graph_id=graph_id,
            user_id=user_id,
            llm_model=llm_model,
            api_key=api_key,
            base_url=base_url,
        )

        yield {"type": "status", "stage": "thinking", "message": "正在分析请求..."}

        # 构建初始消息
        context_summary = {
            "nodes": len(graph_context.get("nodes", [])),
            "edges": len(graph_context.get("edges", [])),
        }

        full_prompt = f"""用户请求: {user_prompt}

当前图状态:
- 节点数: {context_summary["nodes"]}
- 边数: {context_summary["edges"]}

请按照工作流程生成完整的 Agent 工作流图。"""

        # 保存请求
        store.write_request(
            {
                "user_prompt": user_prompt,
                "graph_context_summary": context_summary,
                "conversation_history": conversation_history or [],
            }
        )

        # 收集 actions
        collected_actions: List[Dict[str, Any]] = []
        final_message = ""

        # 流式调用 Manager
        async for event in manager.astream_events(
            {"messages": [HumanMessage(content=full_prompt)]},
            version="v2",
            config={"recursion_limit": 100},
        ):
            event_dict_raw = event if isinstance(event, dict) else {}
            event_dict: Dict[str, Any] = event_dict_raw  # type: ignore[assignment]
            event_kind = event_dict.get("event", "")

            if event_kind == "on_chat_model_stream":
                data = event_dict.get("data", {})
                chunk = data.get("chunk") if isinstance(data, dict) else None
                if chunk and hasattr(chunk, "content") and chunk.content:
                    yield {"type": "content", "content": chunk.content}

            elif event_kind == "on_tool_start":
                tool_name = event_dict.get("name", "")
                data = event_dict.get("data", {})
                tool_input = data.get("input", {}) if isinstance(data, dict) else {}
                yield {
                    "type": "tool_call",
                    "tool": tool_name,
                    "input": tool_input,
                }

                # 识别 task 调用来更新阶段
                if tool_name == "task":
                    subagent = tool_input.get("subagent_type", "") or tool_input.get("name", "")
                    if "analyst" in subagent:
                        yield {"type": "status", "stage": "analyzing", "message": "正在分析需求..."}
                    elif "architect" in subagent:
                        yield {"type": "status", "stage": "planning", "message": "正在设计架构..."}
                    elif "validator" in subagent:
                        yield {"type": "status", "stage": "validating", "message": "正在验证设计..."}

            elif event_kind == "on_tool_end":
                tool_name = event_dict.get("name", "")
                data = event_dict.get("data", {})
                tool_output_raw = data.get("output") if isinstance(data, dict) else None

                if tool_output_raw:
                    action = _parse_tool_output_to_action(tool_output_raw)
                    if action:
                        collected_actions.append(action)
                        yield {"type": "tool_result", "action": action}

            elif event_kind == "on_chat_model_end":
                data = event_dict.get("data", {})
                output = data.get("output") if isinstance(data, dict) else None
                if output and hasattr(output, "content"):
                    final_message = output.content

        # 处理完成
        yield {"type": "status", "stage": "processing", "message": "处理结果..."}

        # 应用自动布局优化坐标
        yield {"type": "status", "stage": "layout", "message": "优化布局..."}
        collected_actions = _apply_layout_to_actions(collected_actions, store)

        # 修复边的节点 ID 映射（blueprint ID -> 实际生成的 ID）
        collected_actions = _fix_edge_node_ids(collected_actions, store)

        # 保存 actions
        store.write_actions(collected_actions)

        # 写入 index
        validation = safe_read_validation(store)
        health_score = validation.health_score if validation else None

        store.write_index(
            {
                "graph_id": graph_id,
                "run_id": store.run_id,
                "user_id": user_id,
                "actions_count": len(collected_actions),
                "health_score": health_score,
                "ok": True,
            }
        )

        # 批量发送最终结果（一次性发送所有 actions，避免前端闪烁）
        yield {
            "type": "result",
            "message": final_message,
            "actions": collected_actions,
            "batch": True,  # 标记为批量操作，前端可一次性执行
        }

        yield {"type": "done"}

        logger.info(f"[DeepAgentsCopilot] Completed run_id={store.run_id} actions={len(collected_actions)}")

    except Exception as e:
        logger.error(f"[DeepAgentsCopilot] Error: {e}")
        yield {"type": "error", "message": str(e)}


# ==================== Schema Validation Helpers ====================


def safe_read_blueprint(store: ArtifactStore) -> Optional[WorkflowBlueprint]:
    """
    安全读取 blueprint，校验失败返回 None。
    使用 Pydantic 模型验证数据结构。
    """
    try:
        if not store.run_dir:
            logger.warning("[DeepAgentsCopilot] Store run_dir is None")
            return None
        blueprint_path = store.run_dir / "blueprint.json"
        if not blueprint_path.exists():
            logger.warning(f"[DeepAgentsCopilot] Blueprint file not found: {blueprint_path}")
            return None

        data = json.loads(blueprint_path.read_text(encoding="utf-8"))
        return WorkflowBlueprint(**data)
    except json.JSONDecodeError as e:
        logger.warning(f"[DeepAgentsCopilot] Blueprint JSON parse error: {e}")
        return None
    except Exception as e:
        logger.warning(f"[DeepAgentsCopilot] Blueprint validation failed: {e}")
        return None


def safe_read_validation(store: ArtifactStore) -> Optional[ValidationReport]:
    """
    安全读取 validation report，校验失败返回 None。
    """
    try:
        if not store.run_dir:
            logger.warning("[DeepAgentsCopilot] Store run_dir is None")
            return None
        validation_path = store.run_dir / "validation.json"
        if not validation_path.exists():
            logger.warning(f"[DeepAgentsCopilot] Validation file not found: {validation_path}")
            return None

        data = json.loads(validation_path.read_text(encoding="utf-8"))
        return ValidationReport(**data)
    except json.JSONDecodeError as e:
        logger.warning(f"[DeepAgentsCopilot] Validation JSON parse error: {e}")
        return None
    except Exception as e:
        logger.warning(f"[DeepAgentsCopilot] Validation report parse failed: {e}")
        return None


def read_and_layout_blueprint(store: ArtifactStore) -> Optional[Dict[str, Any]]:
    """
    读取 blueprint 并应用自动布局。
    返回带有优化坐标的 blueprint 字典。
    """
    blueprint = safe_read_blueprint(store)
    if not blueprint:
        return None

    # 转换为字典
    blueprint_dict = blueprint.model_dump()

    # 计算最优间距
    x_spacing, y_spacing = calculate_optimal_spacing(
        blueprint_dict.get("nodes", []),
        blueprint_dict.get("edges", []),
    )

    # 应用自动布局
    blueprint_dict = apply_auto_layout(
        blueprint_dict,
        x_spacing=x_spacing,
        y_spacing=y_spacing,
    )

    # 居中到画布
    blueprint_dict = center_graph_on_canvas(blueprint_dict)

    logger.info("[DeepAgentsCopilot] Applied auto layout to blueprint")
    return blueprint_dict


# ==================== Helpers ====================


def _extract_actions_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    从 agent 结果中提取 actions。

    使用统一的工具函数提取并展开 actions。

    Returns:
        List of action dicts (not GraphAction objects, for compatibility)
    """
    from app.core.copilot.response_parser import extract_actions_from_agent_result

    # Extract as GraphAction objects, then convert to dicts
    graph_actions = extract_actions_from_agent_result(result, filter_non_actions=False)

    # Convert to dict format for compatibility
    actions = []
    for action in graph_actions:
        actions.append(
            {
                "type": action.type.value,
                "payload": action.payload,
                "reasoning": action.reasoning,
            }
        )

    return actions


def _extract_final_message(result: Dict[str, Any]) -> str:
    """从 agent 结果中提取最终消息"""
    messages = result.get("messages", [])

    for msg in reversed(messages):
        if hasattr(msg, "content") and isinstance(msg.content, str):
            if hasattr(msg, "type") and msg.type == "ai":
                return msg.content
            if msg.__class__.__name__ == "AIMessage":
                return msg.content

    return ""


def _apply_layout_to_actions(actions: List[Dict[str, Any]], store: ArtifactStore) -> List[Dict[str, Any]]:
    """
    应用自动布局优化 actions 中的坐标。

    读取 blueprint，使用布局引擎计算坐标，
    然后更新 CREATE_NODE actions 中的 position。
    """
    # 尝试读取并布局 blueprint
    blueprint_dict = read_and_layout_blueprint(store)
    if not blueprint_dict:
        logger.warning("[DeepAgentsCopilot] Could not apply layout: blueprint not found")
        return actions

    # 构建节点 ID 到坐标的映射
    node_positions: Dict[str, Dict[str, float]] = {}
    for node in blueprint_dict.get("nodes", []):
        node_id = node.get("id")
        position = node.get("position", {})
        if node_id and position:
            node_positions[node_id] = position

    if not node_positions:
        return actions

    # 更新 CREATE_NODE actions 的坐标
    updated_actions = []
    for action in actions:
        if action.get("type") == "CREATE_NODE":
            node_id = action.get("nodeId") or action.get("node_id")
            if node_id and node_id in node_positions:
                new_position = node_positions[node_id]
                action = action.copy()
                if "position" in action:
                    action["position"] = new_position
                elif "payload" in action and isinstance(action["payload"], dict):
                    action["payload"]["position"] = new_position
                logger.debug(f"[DeepAgentsCopilot] Updated position for {node_id}: {new_position}")
        updated_actions.append(action)

    logger.info(f"[DeepAgentsCopilot] Applied layout to {len(node_positions)} nodes")
    return updated_actions


def _fix_edge_node_ids(actions: List[Dict[str, Any]], store: ArtifactStore) -> List[Dict[str, Any]]:
    """
    Fix node IDs in CONNECT_NODES actions.

    Problem: Manager generates CONNECT_NODES using blueprint IDs (manager_001),
    but CREATE_NODE generates new UUIDs (agent_xxx).

    Solution: Build blueprint_id -> actual_id mapping and replace.
    """
    # 1. Build label -> actual_id mapping from CREATE_NODE actions
    label_to_id: Dict[str, str] = {}
    for action in actions:
        if action.get("type") == "CREATE_NODE":
            payload = action.get("payload", {})
            label = payload.get("label")
            node_id = payload.get("id")
            if label and node_id:
                label_to_id[label] = node_id

    if not label_to_id:
        logger.warning("[DeepAgentsCopilot] No CREATE_NODE actions found for ID mapping")
        return actions

    # 2. Read blueprint to get blueprint_id -> label mapping
    blueprint = safe_read_blueprint(store)
    blueprint_id_to_label: Dict[str, str] = {}
    if blueprint:
        for node in blueprint.nodes:
            blueprint_id_to_label[node.id] = node.label

    if not blueprint_id_to_label:
        logger.warning("[DeepAgentsCopilot] No blueprint found for ID mapping")
        return actions

    # 3. Build blueprint_id -> actual_id mapping
    blueprint_to_actual: Dict[str, str] = {}
    for bp_id, label in blueprint_id_to_label.items():
        if label in label_to_id:
            blueprint_to_actual[bp_id] = label_to_id[label]

    logger.info(f"[DeepAgentsCopilot] Built ID mapping: {len(blueprint_to_actual)} nodes")

    # 4. Replace node IDs in CONNECT_NODES actions
    fixed_actions = []
    edges_fixed = 0
    for action in actions:
        if action.get("type") == "CONNECT_NODES":
            payload = action.get("payload", {})
            source = payload.get("source")
            target = payload.get("target")

            new_source = blueprint_to_actual.get(source, source)
            new_target = blueprint_to_actual.get(target, target)

            if new_source != source or new_target != target:
                edges_fixed += 1
                action = action.copy()
                action["payload"] = {
                    "source": new_source,
                    "target": new_target,
                }
                if "reasoning" in payload:
                    action["payload"]["reasoning"] = payload.get("reasoning")
        fixed_actions.append(action)

    logger.info(f"[DeepAgentsCopilot] Fixed {edges_fixed} edge node IDs")
    return fixed_actions


def _parse_tool_output_to_action(tool_output: Any) -> Optional[Dict[str, Any]]:
    """
    解析工具输出为 action。

    使用统一的 parse_tool_output 函数。

    Args:
        tool_output: 工具输出

    Returns:
        解析后的 action dict，如果解析失败则返回 None
    """
    return parse_tool_output(tool_output, tool_name=None)
