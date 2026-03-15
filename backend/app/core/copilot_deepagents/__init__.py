"""
DeepAgents Copilot - 用 DeepAgents 模式生成任意类型的 Agent 工作流图。

架构：
- Manager Agent：编排子代理 + 调用 create_node/connect_nodes
- SubAgents：requirements-analyst, workflow-architect, validator

特点：
- 子代理协作：分析→设计→验证→生成
- 产物落盘：analysis.json, blueprint.json, validation.json
- 标准输出：GraphAction（与现有 Copilot 完全兼容）

使用方式：
    from app.core.copilot_deepagents import stream_deepagents_actions

    async for event in stream_deepagents_actions(
        prompt="创建一个 APK 安全分析团队",
        graph_context={"nodes": [], "edges": []},
        graph_id="my_graph",
    ):
        print(event)
"""

from .manager import DEEPAGENTS_AVAILABLE, run_copilot_manager
from .streaming import stream_deepagents_actions

__all__ = [
    "stream_deepagents_actions",
    "run_copilot_manager",
    "DEEPAGENTS_AVAILABLE",
]
