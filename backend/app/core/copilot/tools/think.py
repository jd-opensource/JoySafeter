"""
Think Tool - Self-reflection and validation for DeepAgents workflows.

Provides think tool for validating DeepAgents workflow structure at different stages.
精简版：专注于两步验证法 - Planning（蓝图阶段）和 Validation（验收阶段）

Enhanced: Validation stage now automatically reads actual nodes and edges from graph_context
to ensure comprehensive detection of all created nodes and connections.
"""

import json
from typing import Dict, List, Optional

from langchain.tools import tool
from loguru import logger
from pydantic import BaseModel, Field

from app.core.copilot.tools.context import get_current_graph_context


class ThinkInput(BaseModel):
    """Input schema for think tool."""

    stage: str = Field(description="验证阶段: 'planning' (创建前) 或 'validation' (完成后)")
    reflection: str = Field(description="当前思路或对任务的理解")
    nodes: Optional[List[str]] = Field(
        default=None,
        description="角色列表或已创建的节点名。在 validation 阶段，如果未提供，将自动从 graph_context 读取",
    )
    connections: Optional[List[str]] = Field(
        default=None,
        description="连接关系，如 ['Manager -> Analyst']。在 validation 阶段，如果未提供，将自动从 graph_context 读取",
    )


@tool(
    args_schema=ThinkInput,
    description="Self-reflection tool for DeepAgents workflow validation. Use at planning (before creating) and validation (after completion) stages. In validation stage, automatically reads actual nodes and edges from graph_context if not provided.",
)
def think(
    stage: str,
    reflection: str,
    nodes: Optional[List[str]] = None,
    connections: Optional[List[str]] = None,
) -> str:
    """
    精简版 Think Tool：专注于 DeepAgents 核心架构验证

    Enhanced: In validation stage, automatically reads actual nodes and edges from graph_context
    if not provided, ensuring comprehensive detection of all created nodes and connections.

    Args:
        stage: 'planning' (创建前) 或 'validation' (完成后)
        reflection: 当前思路或对任务的理解
        nodes: 角色列表或已创建的节点名（validation 阶段可选，会自动从 graph_context 读取）
        connections: 连接关系，如 ['Manager -> Analyst']（validation 阶段可选，会自动从 graph_context 读取）

    Returns:
        JSON with validation feedback and recommendations.

    Note: Use planning stage FIRST for DeepAgents workflows. See system prompt for validation criteria.
    """
    logger.info(
        f"[think] 开始执行验证 stage={stage}, nodes_count={len(nodes) if nodes else 0}, connections_count={len(connections) if connections else 0}"
    )
    logger.debug(
        f"[think] reflection={reflection[:100]}..." if len(reflection) > 100 else f"[think] reflection={reflection}"
    )

    issues = []
    recommendations = []
    consistency_issues = []
    auto_read_used = False  # 标记是否使用了自动读取

    # ---------- 0. VALIDATION 阶段：自动从 graph_context 读取实际节点和连线 ----------
    if stage == "validation":
        logger.debug("[think] validation 阶段：开始从 graph_context 读取实际节点和连线")
        graph_context = get_current_graph_context()
        actual_nodes_data = graph_context.get("nodes", [])
        actual_edges_data = graph_context.get("edges", [])

        logger.debug(
            f"[think] 从 graph_context 读取到 {len(actual_nodes_data)} 个节点，{len(actual_edges_data)} 条连线"
        )
        graph_context = get_current_graph_context()
        actual_nodes_data = graph_context.get("nodes", [])
        actual_edges_data = graph_context.get("edges", [])

        # 从实际 graph_context 提取节点名称
        actual_node_names = []
        actual_node_id_to_label = {}
        for node in actual_nodes_data:
            node_id = node.get("id", "")
            data = node.get("data", {})
            label = data.get("label", node_id)
            actual_node_names.append(label)
            actual_node_id_to_label[node_id] = label

        # 从实际 graph_context 提取连线关系
        actual_connections = []
        for edge in actual_edges_data:
            source_id = edge.get("source", "")
            target_id = edge.get("target", "")
            source_label = actual_node_id_to_label.get(source_id, source_id)
            target_label = actual_node_id_to_label.get(target_id, target_id)
            actual_connections.append(f"{source_label} -> {target_label}")

        # 如果传入了 nodes/connections，进行一致性检查
        if nodes is not None:
            logger.debug(f"[think] 进行节点一致性检查：传入 {len(nodes)} 个节点，实际 {len(actual_node_names)} 个节点")
            # 检查传入的节点是否都在实际创建的节点中
            provided_nodes_lower = {n.lower() for n in nodes}
            actual_nodes_lower = {n.lower() for n in actual_node_names}

            missing_in_actual = provided_nodes_lower - actual_nodes_lower
            missing_in_provided = actual_nodes_lower - provided_nodes_lower

            if missing_in_actual:
                logger.warning(
                    f"[think] 一致性检查：传入的节点 '{', '.join(missing_in_actual)}' 在实际创建的节点中不存在"
                )
                consistency_issues.append(f"传入的节点 '{', '.join(missing_in_actual)}' 在实际创建的节点中不存在")
            if missing_in_provided:
                logger.warning(
                    f"[think] 一致性检查：实际创建的节点 '{', '.join(missing_in_provided)}' 未在传入参数中提及"
                )
                consistency_issues.append(f"实际创建的节点 '{', '.join(missing_in_provided)}' 未在传入参数中提及")
            if not missing_in_actual and not missing_in_provided:
                logger.debug("[think] 节点一致性检查通过：传入节点与实际节点完全匹配")
        else:
            # 如果没有传入，使用实际的节点
            logger.info(f"[think] 未传入 nodes 参数，自动使用 graph_context 中的 {len(actual_node_names)} 个节点")
            nodes = actual_node_names
            auto_read_used = True

        # 如果传入了 connections，进行一致性检查
        if connections is not None:
            logger.debug(
                f"[think] 进行连线一致性检查：传入 {len(connections)} 条连线，实际 {len(actual_connections)} 条连线"
            )
            # 检查传入的连线是否都在实际创建的连线中
            provided_conns_lower = {c.lower().strip() for c in connections}
            actual_conns_lower = {c.lower().strip() for c in actual_connections}

            missing_in_actual = provided_conns_lower - actual_conns_lower
            missing_in_provided = actual_conns_lower - provided_conns_lower

            if missing_in_actual:
                logger.warning(
                    f"[think] 一致性检查：传入的连线 '{', '.join(missing_in_actual)}' 在实际创建的连线中不存在"
                )
                consistency_issues.append(f"传入的连线 '{', '.join(missing_in_actual)}' 在实际创建的连线中不存在")
            if missing_in_provided:
                logger.warning(
                    f"[think] 一致性检查：实际创建的连线 '{', '.join(missing_in_provided)}' 未在传入参数中提及"
                )
                consistency_issues.append(f"实际创建的连线 '{', '.join(missing_in_provided)}' 未在传入参数中提及")
            if not missing_in_actual and not missing_in_provided:
                logger.debug("[think] 连线一致性检查通过：传入连线与实际连线完全匹配")
        else:
            # 如果没有传入，使用实际的连线
            logger.info(
                f"[think] 未传入 connections 参数，自动使用 graph_context 中的 {len(actual_connections)} 条连线"
            )
            connections = actual_connections
            auto_read_used = True

    # 如果 nodes 仍然为 None（planning 阶段且未传入），使用空列表
    if nodes is None:
        nodes = []

    # 基础数据准备
    [n.lower() for n in nodes]
    manager_nodes = [n for n in nodes if "manager" in n.lower() or "coordinator" in n.lower()]
    subagents = [n for n in nodes if n not in manager_nodes]

    logger.debug(f"[think] 节点分析：Manager={len(manager_nodes)} 个，SubAgent={len(subagents)} 个")

    # ---------- 1. PLANNING 阶段：逻辑验证 ----------
    if stage == "planning":
        logger.debug("[think] 执行 planning 阶段验证")

        # Planning 阶段：如果 nodes 为空，说明还没有传入计划，跳过验证
        if not nodes:
            logger.info("[think] planning 阶段：nodes 为空，跳过验证（计划尚未提供）")
            # 不添加任何 issues，直接返回通过
        else:
            # 只有当 nodes 不为空时，才进行验证
            logger.debug(f"[think] planning 阶段：验证 {len(nodes)} 个计划节点")

            # 1.1 Manager 检查
            if not manager_nodes:
                issues.append("DeepAgents 架构必须包含一个 Manager 节点")

            # 1.2 数量检查 (3-8 规范)
            if len(subagents) < 3:
                issues.append(f"SubAgent 数量过少 ({len(subagents)})，建议 3-8 个以保证协作深度")
            elif len(subagents) > 8:
                issues.append(f"SubAgent 数量过多 ({len(subagents)})，建议拆分或合并至 8 个以内")

            # 1.3 职责单一性
            for node in nodes:
                if " and " in node.lower() or "&" in node:
                    issues.append(f"角色 '{node}' 职责模糊，建议拆分为两个独立 Agent")

    # ---------- 2. VALIDATION 阶段：拓扑验证 ----------
    elif stage == "validation":
        logger.debug("[think] 执行 validation 阶段验证")
        # 2.1 基础完整性
        if len(manager_nodes) != 1:
            logger.warning(f"[think] Manager 数量检查失败：期望 1 个，实际 {len(manager_nodes)} 个")
            issues.append(f"必须有且仅有一个 Manager，当前发现 {len(manager_nodes)} 个")
        else:
            logger.debug("[think] Manager 数量检查通过：1 个")

        # 2.2 星型拓扑检查 (核心)
        if connections:
            logger.debug(f"[think] 开始星型拓扑检查，连接数={len(connections)}")
            conn_map: Dict[str, List[str]] = {n.lower(): [] for n in nodes}
            for c in connections:
                if "->" in c:
                    src, tgt = [p.strip().lower() for p in c.split("->")]
                    if src in conn_map:
                        conn_map[src].append(tgt)

            # 检查 Manager 是否连接了所有 SubAgent
            if manager_nodes:
                mgr_lower = manager_nodes[0].lower()
                disconnected_subagents = []
                for sa in subagents:
                    if sa.lower() not in conn_map.get(mgr_lower, []):
                        disconnected_subagents.append(sa)
                        issues.append(f"断连：Manager 未连接到 {sa}")

                if disconnected_subagents:
                    logger.warning(
                        f"[think] 星型拓扑检查：Manager 未连接到 {len(disconnected_subagents)} 个 SubAgent: {', '.join(disconnected_subagents)}"
                    )
                else:
                    logger.debug(f"[think] 星型拓扑检查：Manager 已连接到所有 {len(subagents)} 个 SubAgent")

            # 检查是否有 SubAgent 之间的链式连接 (Anti-pattern)
            subagent_with_children = []
            for sa in subagents:
                if conn_map.get(sa.lower()):
                    subagent_with_children.append(sa)
                    issues.append(f"检测到非星型连接：{sa} 拥有下游节点，请改为由 Manager 统一调度")

            if subagent_with_children:
                logger.warning(
                    f"[think] 星型拓扑检查：发现 {len(subagent_with_children)} 个 SubAgent 拥有下游节点（违反星型拓扑）: {', '.join(subagent_with_children)}"
                )
            else:
                logger.debug("[think] 星型拓扑检查：未发现 SubAgent 之间的连接（符合星型拓扑）")
        else:
            logger.warning("[think] 未检测到任何连接关系")
            issues.append("未检测到任何连接关系")

    else:
        issues.append(f"未知的验证阶段: {stage}。有效阶段为 'planning' 或 'validation'")

    # ---------- 3. 合并一致性检查问题 ----------
    if consistency_issues:
        logger.info(f"[think] 发现 {len(consistency_issues)} 个一致性问题")
        issues.extend([f"一致性检查: {issue}" for issue in consistency_issues])

    # ---------- 4. 生成反馈 ----------
    passed = len(issues) == 0
    if passed:
        logger.info(f"[think] 验证通过：stage={stage}, nodes={len(nodes)}, connections={len(connections or [])}")
        recommendations = [
            "✓ 结构符合 DeepAgents 最佳实践",
            "可以开始执行下个阶段" if stage == "planning" else "已准备好交付结果",
        ]
    else:
        logger.warning(
            f"[think] 验证失败：stage={stage}, issues={len(issues)}, nodes={len(nodes)}, connections={len(connections or [])}"
        )
        recommendations = [f"⚠️ 待优化: {i}" for i in issues]

    # 构建反馈摘要
    summary_parts = [f"已完成对 {len(nodes)} 个节点和 {len(connections or [])} 条连接的扫描"]
    if auto_read_used:
        summary_parts.append("（已自动从 graph_context 读取实际数据）")
    if consistency_issues:
        summary_parts.append(f"发现 {len(consistency_issues)} 个一致性问题")

    result = json.dumps(
        {
            "type": "THINK",
            "feedback": {
                "stage": stage,
                "passed": passed,
                "issues_found": len(issues),
                "consistency_issues": len(consistency_issues) if consistency_issues else 0,
                "recommendations": recommendations,
                "summary": " | ".join(summary_parts),
            },
        },
        ensure_ascii=False,
        indent=2,
    )

    logger.info(
        f"[think] 验证完成：stage={stage}, passed={passed}, issues={len(issues)}, consistency_issues={len(consistency_issues)}"
    )
    logger.debug(f"[think] 返回结果摘要：{summary_parts[0]}")

    return result
