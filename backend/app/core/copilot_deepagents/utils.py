"""
Utility functions for Copilot DeepAgents.

Breaking circular dependencies by moving shared helper functions
between manager and runner here.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from loguru import logger

from .artifacts import ArtifactStore
from .layout import apply_auto_layout, calculate_optimal_spacing, center_graph_on_canvas
from .schemas import ValidationReport, WorkflowBlueprint


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
    from app.core.copilot.tool_output_parser import parse_tool_output

    return parse_tool_output(tool_output, tool_name=None)
