"""
DeepAgents Copilot Manager.

用 DeepAgents 的 Manager + 子代理模式来生成任意类型的图：
- Manager：编排子代理、调用 create_node/connect_nodes 工具输出 GraphAction
- 子代理：规划/设计/验证，产出思考文件
- 最终输出：标准 GraphAction（与现有 Copilot 完全兼容）
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Type

if TYPE_CHECKING:
    from deepagents import SubAgent as SubAgentT
    from deepagents.backends.filesystem import FilesystemBackend as FilesystemBackendT

from langchain_core.runnables import Runnable
from loguru import logger

from app.core.agent.sample_agent import get_default_model
from app.core.copilot.tools import connect_nodes, create_node, delete_node, update_config

from .artifacts import ArtifactStore
from .prompts import (
    MANAGER_SYSTEM_PROMPT,
    REQUIREMENTS_ANALYST_PROMPT,
    VALIDATOR_PROMPT,
    WORKFLOW_ARCHITECT_PROMPT,
)

# ==================== Optional deepagents imports ====================
# 先声明为可选，避免在 except 中赋 None 触发 mypy "Cannot assign to a type"
create_deep_agent: Any = None
FilesystemMiddleware: Type[Any] | None = None
FilesystemBackend: Type[Any] | None = None
SubAgent: Type[Any] | None = None
DEEPAGENTS_AVAILABLE = False

try:
    from deepagents import (
        FilesystemMiddleware as _FilesystemMiddleware,
    )
    from deepagents import (
        SubAgent as _SubAgent,
    )
    from deepagents import (
        create_deep_agent as _create_deep_agent,
    )
    from deepagents.backends.filesystem import FilesystemBackend as _FilesystemBackend

    create_deep_agent = _create_deep_agent
    FilesystemMiddleware = _FilesystemMiddleware
    FilesystemBackend = _FilesystemBackend
    SubAgent = _SubAgent
    DEEPAGENTS_AVAILABLE = True
except ImportError:
    logger.warning("[DeepAgentsCopilot] deepagents library not available")

# ==================== Manager Factory ====================


def get_artifacts_root() -> Path:
    """获取产物根目录"""
    root = os.environ.get("DEEPAGENTS_ARTIFACTS_DIR", "")
    if not root:
        root = str(Path.home() / ".agent-platform" / "deepagents")
    return Path(root)


def _build_subagents(backend: "FilesystemBackendT") -> List["SubAgentT"]:
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
    if not DEEPAGENTS_AVAILABLE or create_deep_agent is None or FilesystemBackend is None:
        raise RuntimeError("deepagents library not available. Install with: pip install deepagents")
    assert create_deep_agent is not None and FilesystemBackend is not None  # 供 mypy 收窄类型

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


# ==================== Schema Validation Helpers (Moved to .utils) ====================

# Re-exporting from .utils if needed, but better to import directly from .utils

# ==================== Helpers (Moved to .utils) ====================
