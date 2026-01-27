"""
DeepAgents Copilot - SubAgent Definitions.

子代理只做"思考"并将产物写入文件，不调用 Copilot 工具（create_node 等）。
最终由 Manager 读取产物后调用 Copilot 工具输出标准 GraphAction。

子代理：
- requirements-analyst: 分析需求、识别复杂度
- workflow-architect: 设计 ReactFlow 兼容的节点/边结构
- validator: 校验 blueprint 结构

注意：实际的 SubAgent specs 在 manager.py 中定义，因为需要与 FilesystemMiddleware 配合。
这个文件保留用于文档和可能的扩展。
"""

from __future__ import annotations

from typing import Any, Dict, List

# ==================== SubAgent Names ====================

SUBAGENT_REQUIREMENTS_ANALYST = "requirements-analyst"
SUBAGENT_WORKFLOW_ARCHITECT = "workflow-architect"
SUBAGENT_VALIDATOR = "validator"

ALL_SUBAGENTS = [
    SUBAGENT_REQUIREMENTS_ANALYST,
    SUBAGENT_WORKFLOW_ARCHITECT,
    SUBAGENT_VALIDATOR,
]


# ==================== Output File Paths ====================

ANALYSIS_FILE = "/analysis.json"
BLUEPRINT_FILE = "/blueprint.json"
VALIDATION_FILE = "/validation.json"


def get_subagent_specs() -> List[Dict[str, Any]]:
    """
    返回子代理配置列表。

    注意：这个函数已弃用，实际的 specs 在 manager.py 的 _build_subagents 中定义。
    保留此函数用于向后兼容。
    """
    from .manager import REQUIREMENTS_ANALYST_PROMPT, VALIDATOR_PROMPT, WORKFLOW_ARCHITECT_PROMPT

    return [
        {
            "name": SUBAGENT_REQUIREMENTS_ANALYST,
            "description": "分析用户请求，识别需求复杂度、DeepAgents 适用性",
            "system_prompt": REQUIREMENTS_ANALYST_PROMPT,
            "tools": [],
        },
        {
            "name": SUBAGENT_WORKFLOW_ARCHITECT,
            "description": "设计 ReactFlow 兼容的节点/边结构，生成 blueprint",
            "system_prompt": WORKFLOW_ARCHITECT_PROMPT,
            "tools": [],
        },
        {
            "name": SUBAGENT_VALIDATOR,
            "description": "校验 blueprint 结构，发现问题并给出修复建议",
            "system_prompt": VALIDATOR_PROMPT,
            "tools": [],
        },
    ]
