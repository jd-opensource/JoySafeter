"""
Think Tool - Self-reflection and validation for DeepAgents workflows.

Provides think tool for validating DeepAgents workflow structure at different stages.
Simplified: focus on two-step validation - Planning (blueprint stage) and Validation (acceptance stage).

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

    stage: str = Field(description="Validation stage: 'planning' (before creation) or 'validation' (after completion)")
    reflection: str = Field(description="Current reasoning or understanding of the task")
    nodes: Optional[List[str]] = Field(
        default=None,
        description="Role list or created node names. In validation stage, auto-read from graph_context if not provided",
    )
    connections: Optional[List[str]] = Field(
        default=None,
        description="Connection relationships, e.g. ['Manager -> Analyst']. In validation stage, auto-read from graph_context if not provided",
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
    Simplified Think Tool: focus on DeepAgents core architecture validation.

    Enhanced: In validation stage, automatically reads actual nodes and edges from graph_context
    if not provided, ensuring comprehensive detection of all created nodes and connections.

    Args:
        stage: 'planning' (before creation) or 'validation' (after completion)
        reflection: current reasoning or understanding of the task
        nodes: role list or created node names (optional in validation stage; auto-read from graph_context)
        connections: connection relationships, e.g. ['Manager -> Analyst'] (optional in validation stage; auto-read from graph_context)

    Returns:
        JSON with validation feedback and recommendations.

    Note: Use planning stage FIRST for DeepAgents workflows. See system prompt for validation criteria.
    """
    logger.info(
        f"[think] starting validation stage={stage}, nodes_count={len(nodes) if nodes else 0}, connections_count={len(connections) if connections else 0}"
    )
    logger.debug(
        f"[think] reflection={reflection[:100]}..." if len(reflection) > 100 else f"[think] reflection={reflection}"
    )

    issues = []
    recommendations = []
    consistency_issues = []
    auto_read_used = False  # track whether auto-read was used

    # ---------- 0. VALIDATION stage: auto-read actual nodes and edges from graph_context ----------
    if stage == "validation":
        logger.debug("[think] validation stage: reading actual nodes and edges from graph_context")
        graph_context = get_current_graph_context()
        actual_nodes_data = graph_context.get("nodes", [])
        actual_edges_data = graph_context.get("edges", [])

        logger.debug(
            f"[think] read {len(actual_nodes_data)} nodes and {len(actual_edges_data)} edges from graph_context"
        )

        # extract node names from actual graph_context
        actual_node_names = []
        actual_node_id_to_label = {}
        for node in actual_nodes_data:
            node_id = node.get("id", "")
            data = node.get("data", {})
            label = data.get("label", node_id)
            actual_node_names.append(label)
            actual_node_id_to_label[node_id] = label

        # extract edge relationships from actual graph_context
        actual_connections = []
        for edge in actual_edges_data:
            source_id = edge.get("source", "")
            target_id = edge.get("target", "")
            source_label = actual_node_id_to_label.get(source_id, source_id)
            target_label = actual_node_id_to_label.get(target_id, target_id)
            actual_connections.append(f"{source_label} -> {target_label}")

        # if nodes/connections were provided, perform consistency check
        if nodes is not None:
            logger.debug(
                f"[think] node consistency check: provided {len(nodes)} nodes, actual {len(actual_node_names)} nodes"
            )
            # check whether provided nodes exist in actually created nodes
            provided_nodes_lower = {n.lower() for n in nodes}
            actual_nodes_lower = {n.lower() for n in actual_node_names}

            missing_in_actual = provided_nodes_lower - actual_nodes_lower
            missing_in_provided = actual_nodes_lower - provided_nodes_lower

            if missing_in_actual:
                logger.warning(
                    f"[think] consistency check: provided nodes '{', '.join(missing_in_actual)}' not found in actual nodes"
                )
                consistency_issues.append(f"Provided nodes '{', '.join(missing_in_actual)}' not found in actual nodes")
            if missing_in_provided:
                logger.warning(
                    f"[think] consistency check: actual nodes '{', '.join(missing_in_provided)}' not mentioned in provided params"
                )
                consistency_issues.append(
                    f"Actual nodes '{', '.join(missing_in_provided)}' not mentioned in provided params"
                )
            if not missing_in_actual and not missing_in_provided:
                logger.debug("[think] node consistency check passed: provided nodes match actual nodes")
        else:
            # if not provided, use actual nodes
            logger.info(
                f"[think] nodes param not provided, auto-using {len(actual_node_names)} nodes from graph_context"
            )
            nodes = actual_node_names
            auto_read_used = True

        # if connections were provided, perform consistency check
        if connections is not None:
            logger.debug(
                f"[think] edge consistency check: provided {len(connections)} edges, actual {len(actual_connections)} edges"
            )
            # check whether provided edges exist in actually created edges
            provided_conns_lower = {c.lower().strip() for c in connections}
            actual_conns_lower = {c.lower().strip() for c in actual_connections}

            missing_in_actual = provided_conns_lower - actual_conns_lower
            missing_in_provided = actual_conns_lower - provided_conns_lower

            if missing_in_actual:
                logger.warning(
                    f"[think] consistency check: provided edges '{', '.join(missing_in_actual)}' not found in actual edges"
                )
                consistency_issues.append(f"Provided edges '{', '.join(missing_in_actual)}' not found in actual edges")
            if missing_in_provided:
                logger.warning(
                    f"[think] consistency check: actual edges '{', '.join(missing_in_provided)}' not mentioned in provided params"
                )
                consistency_issues.append(
                    f"Actual edges '{', '.join(missing_in_provided)}' not mentioned in provided params"
                )
            if not missing_in_actual and not missing_in_provided:
                logger.debug("[think] edge consistency check passed: provided edges match actual edges")
        else:
            # if not provided, use actual edges
            logger.info(
                f"[think] connections param not provided, auto-using {len(actual_connections)} edges from graph_context"
            )
            connections = actual_connections
            auto_read_used = True

    # if nodes is still None (planning stage with no input), use empty list
    if nodes is None:
        nodes = []

    # prepare base data
    manager_nodes = [n for n in nodes if "manager" in n.lower() or "coordinator" in n.lower()]
    subagents = [n for n in nodes if n not in manager_nodes]

    logger.debug(f"[think] node analysis: Manager={len(manager_nodes)}, SubAgent={len(subagents)}")

    # ---------- 1. PLANNING stage: logic validation ----------
    if stage == "planning":
        logger.debug("[think] running planning stage validation")

        # planning stage: if nodes is empty, plan has not been provided yet; skip validation
        if not nodes:
            logger.info("[think] planning stage: nodes is empty, skipping validation (plan not yet provided)")
            # add no issues; return pass
        else:
            # only validate when nodes is non-empty
            logger.debug(f"[think] planning stage: validating {len(nodes)} planned nodes")

            # 1.1 manager check
            if not manager_nodes:
                issues.append("DeepAgents architecture must include a Manager node")

            # 1.2 count check (3-8 guideline)
            if len(subagents) < 3:
                issues.append(f"Too few SubAgents ({len(subagents)}), recommend 3-8 for effective collaboration")
            elif len(subagents) > 8:
                issues.append(f"Too many SubAgents ({len(subagents)}), recommend splitting or merging to 8 or fewer")

            # 1.3 single responsibility check
            for node in nodes:
                if " and " in node.lower() or "&" in node:
                    issues.append(
                        f"Role '{node}' has ambiguous responsibilities, consider splitting into two separate Agents"
                    )

    # ---------- 2. VALIDATION stage: topology validation ----------
    elif stage == "validation":
        logger.debug("[think] running validation stage checks")
        # 2.1 basic completeness
        if len(manager_nodes) != 1:
            logger.warning(f"[think] Manager count check failed: expected 1, found {len(manager_nodes)}")
            issues.append(f"Must have exactly one Manager, found {len(manager_nodes)}")
        else:
            logger.debug("[think] Manager count check passed: 1")

        # 2.2 star topology check (core)
        if connections:
            logger.debug(f"[think] starting star topology check, connections={len(connections)}")
            conn_map: Dict[str, List[str]] = {n.lower(): [] for n in nodes}
            for c in connections:
                if "->" in c:
                    src, tgt = [p.strip().lower() for p in c.split("->")]
                    if src in conn_map:
                        conn_map[src].append(tgt)

            # check whether Manager is connected to all SubAgents
            if manager_nodes:
                mgr_lower = manager_nodes[0].lower()
                disconnected_subagents = []
                for sa in subagents:
                    if sa.lower() not in conn_map.get(mgr_lower, []):
                        disconnected_subagents.append(sa)
                        issues.append(f"Disconnected: Manager is not connected to {sa}")

                if disconnected_subagents:
                    logger.warning(
                        f"[think] star topology check: Manager not connected to {len(disconnected_subagents)} SubAgents: {', '.join(disconnected_subagents)}"
                    )
                else:
                    logger.debug(f"[think] star topology check: Manager connected to all {len(subagents)} SubAgents")

            # check for chain connections between SubAgents (anti-pattern)
            subagent_with_children = []
            for sa in subagents:
                if conn_map.get(sa.lower()):
                    subagent_with_children.append(sa)
                    issues.append(
                        f"Non-star connection detected: {sa} has downstream nodes, let Manager coordinate instead"
                    )

            if subagent_with_children:
                logger.warning(
                    f"[think] star topology check: found {len(subagent_with_children)} SubAgents with downstream nodes (violates star topology): {', '.join(subagent_with_children)}"
                )
            else:
                logger.debug("[think] star topology check: no inter-SubAgent connections found (star topology OK)")
        else:
            logger.warning("[think] no connections detected")
            issues.append("No connections detected")

    else:
        issues.append(f"Unknown validation stage: {stage}. Valid stages are 'planning' or 'validation'")

    # ---------- 3. merge consistency check issues ----------
    if consistency_issues:
        logger.info(f"[think] found {len(consistency_issues)} consistency issues")
        issues.extend([f"Consistency check: {issue}" for issue in consistency_issues])

    # ---------- 4. generate feedback ----------
    passed = len(issues) == 0
    if passed:
        logger.info(
            f"[think] validation passed: stage={stage}, nodes={len(nodes)}, connections={len(connections or [])}"
        )
        recommendations = [
            "Structure follows DeepAgents best practices",
            "Ready to proceed to next stage" if stage == "planning" else "Ready to deliver results",
        ]
    else:
        logger.warning(
            f"[think] validation failed: stage={stage}, issues={len(issues)}, nodes={len(nodes)}, connections={len(connections or [])}"
        )
        recommendations = [f"Needs improvement: {i}" for i in issues]

    # build feedback summary
    summary_parts = [f"Scanned {len(nodes)} nodes and {len(connections or [])} connections"]
    if auto_read_used:
        summary_parts.append("(auto-read actual data from graph_context)")
    if consistency_issues:
        summary_parts.append(f"Found {len(consistency_issues)} consistency issues")

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
        f"[think] validation complete: stage={stage}, passed={passed}, issues={len(issues)}, consistency_issues={len(consistency_issues)}"
    )
    logger.debug(f"[think] result summary: {summary_parts[0]}")

    return result
