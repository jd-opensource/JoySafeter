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
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Type

if TYPE_CHECKING:
    from deepagents import SubAgent as SubAgentT
    from deepagents.backends.filesystem import FilesystemBackend as FilesystemBackendT

from langchain_core.runnables import Runnable
from loguru import logger

from app.core.agent.sample_agent import get_default_model
from app.core.copilot.tool_output_parser import parse_tool_output
from app.core.copilot.tools import connect_nodes, create_node, delete_node, update_config

from .artifacts import ArtifactStore
from .layout import apply_auto_layout, calculate_optimal_spacing, center_graph_on_canvas
from .schemas import ValidationReport, WorkflowBlueprint

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

# ==================== Prompts (from prompts.py) ====================

from .prompts import (
    MANAGER_SYSTEM_PROMPT,
    REQUIREMENTS_ANALYST_PROMPT,
    VALIDATOR_PROMPT,
    WORKFLOW_ARCHITECT_PROMPT,
)


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


# Re-export runner entry points so existing imports from manager still work
from .runner import run_copilot_manager, stream_copilot_manager  # noqa: E402

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

    # 更新 CREATE_NODE actions 的坐标（action 结构为 {type, payload: {id, ...}, reasoning}）
    updated_actions = []
    for action in actions:
        if action.get("type") == "CREATE_NODE":
            payload = action.get("payload") or {}
            node_id = payload.get("id") if isinstance(payload, dict) else None
            if node_id and node_id in node_positions:
                new_position = node_positions[node_id]
                action = action.copy()
                payload = action.get("payload")
                if isinstance(payload, dict):
                    action["payload"] = {**payload, "position": new_position}
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
