"""
Analysis Tools - Workflow analysis and optimization.

Provides analyze_workflow tool for analyzing graph structure and providing recommendations.
"""

import json
from typing import Dict, List

from langchain.tools import tool
from pydantic import BaseModel, Field

from app.core.copilot.tools.context import get_current_graph_context


class AnalyzeWorkflowInput(BaseModel):
    """Input schema for analyze_workflow tool."""

    analysis_type: str = Field(
        default="comprehensive",
        description="Type of analysis: 'comprehensive' (all checks), 'bottleneck' (performance issues), 'complexity' (complexity metrics), 'coverage' (missing handlers), 'quality' (best practices)",
    )
    reasoning: str = Field(description="Explanation for why analysis is needed")


@tool(
    args_schema=AnalyzeWorkflowInput,
    description="Analyze workflow structure and provide optimization suggestions. Analysis types: comprehensive, bottleneck, complexity, coverage, quality.",
)
def analyze_workflow(
    reasoning: str,
    analysis_type: str = "comprehensive",
) -> str:
    """
    Analyze workflow and provide optimization suggestions.

    Args:
        reasoning: Why analysis is needed
        analysis_type: 'comprehensive' (default), 'bottleneck', 'complexity', 'coverage', 'quality'

    Returns:
        JSON with analysis results, issues, and recommendations.
    """
    graph_context = get_current_graph_context()

    nodes = graph_context.get("nodes", [])
    edges = graph_context.get("edges", [])

    if not nodes:
        return json.dumps(
            {
                "error": "No nodes in the current graph to analyze",
                "suggestion": "Create some nodes first before running analysis",
            },
            ensure_ascii=False,
        )

    analysis_result = {
        "analysis_type": analysis_type,
        "reasoning": reasoning,
        "summary": {},
        "issues": [],
        "recommendations": [],
        "metrics": {},
    }

    # Build adjacency structures
    outgoing: Dict[str, List[str]] = {n.get("id"): [] for n in nodes}
    incoming: Dict[str, List[str]] = {n.get("id"): [] for n in nodes}

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src in outgoing and tgt in incoming:
            outgoing[src].append(tgt)
            incoming[tgt].append(src)

    # Find structural elements
    root_nodes = [n for n in nodes if not incoming.get(n.get("id"), [])]
    leaf_nodes = [n for n in nodes if not outgoing.get(n.get("id"), [])]

    # Count node types
    node_types: Dict[str, int] = {}
    for node in nodes:
        data = node.get("data", {})
        node_type = data.get("type", "unknown")
        node_types[node_type] = node_types.get(node_type, 0) + 1

    # Basic metrics
    analysis_result["metrics"] = {
        "total_nodes": len(nodes),
        "total_edges": len(edges),
        "root_nodes": len(root_nodes),
        "leaf_nodes": len(leaf_nodes),
        "node_types": node_types,
        "avg_connections": round(len(edges) / max(len(nodes), 1), 2),
    }

    # Analysis checks
    issues = []
    recommendations = []

    # Check 1: Dead ends (leaf nodes that are not direct_reply or human_input)
    for node in leaf_nodes:
        data = node.get("data", {})
        node_type = data.get("type", "")
        label = data.get("label", node.get("id"))
        if node_type not in ["direct_reply", "human_input"]:
            issues.append(
                {
                    "type": "dead_end",
                    "severity": "warning",
                    "node_id": node.get("id"),
                    "message": f"Node '{label}' has no outgoing edges - workflow may end unexpectedly",
                }
            )
            recommendations.append(f"Add an outgoing edge from '{label}' or convert to a terminal node")

    # Check 2: Orphan nodes (no connections at all)
    for node in nodes:
        node_id = node.get("id")
        label = node.get("data", {}).get("label", node_id)
        if not incoming.get(node_id) and not outgoing.get(node_id) and len(nodes) > 1:
            issues.append(
                {
                    "type": "orphan_node",
                    "severity": "error",
                    "node_id": node_id,
                    "message": f"Node '{label}' is not connected to any other node",
                }
            )
            recommendations.append(f"Connect '{label}' to the workflow or remove it")

    # Check 3: Multiple root nodes (might be intentional, but worth noting)
    if len(root_nodes) > 1:
        issues.append(
            {
                "type": "multiple_entry_points",
                "severity": "info",
                "message": f"Workflow has {len(root_nodes)} entry points - ensure this is intentional",
            }
        )

    # Check 4: Missing systemPrompts for agent nodes
    for node in nodes:
        data = node.get("data", {})
        if data.get("type") == "agent":
            config = data.get("config", {})
            system_prompt = config.get("systemPrompt", "")
            label = data.get("label", node.get("id"))
            if not system_prompt or len(system_prompt) < 50:
                issues.append(
                    {
                        "type": "weak_prompt",
                        "severity": "warning",
                        "node_id": node.get("id"),
                        "message": f"Agent '{label}' has a weak or missing systemPrompt",
                    }
                )
                recommendations.append(f"Improve systemPrompt for '{label}' with specific instructions")

    # Check 5: DeepAgents without children
    for node in nodes:
        data = node.get("data", {})
        config = data.get("config", {})
        if config.get("useDeepAgents"):
            node_id = node.get("id")
            label = data.get("label", node_id)
            children = outgoing.get(node_id, [])
            if not children:
                issues.append(
                    {
                        "type": "deep_agent_no_children",
                        "severity": "error",
                        "node_id": node_id,
                        "message": f"DeepAgent '{label}' has no subagent children",
                    }
                )
                recommendations.append(f"Add subagent nodes connected to '{label}'")

    # Check 6: Condition nodes without both branches
    for node in nodes:
        data = node.get("data", {})
        if data.get("type") in ["condition", "condition_agent"]:
            node_id = node.get("id")
            label = data.get("label", node_id)
            out_edges = outgoing.get(node_id, [])
            if len(out_edges) < 2:
                issues.append(
                    {
                        "type": "incomplete_branching",
                        "severity": "warning",
                        "node_id": node_id,
                        "message": f"Condition '{label}' has only {len(out_edges)} outgoing edges (expected 2+)",
                    }
                )
                recommendations.append(f"Add missing branch(es) from '{label}'")

    # Summary
    error_count = len([i for i in issues if i.get("severity") == "error"])
    warning_count = len([i for i in issues if i.get("severity") == "warning"])
    info_count = len([i for i in issues if i.get("severity") == "info"])

    analysis_result["summary"] = {
        "health_score": max(0, 100 - error_count * 20 - warning_count * 5),
        "errors": error_count,
        "warnings": warning_count,
        "info": info_count,
        "status": "healthy" if error_count == 0 else "needs_attention" if warning_count > 0 else "critical",
    }

    analysis_result["issues"] = issues  # type: ignore[assignment]
    analysis_result["recommendations"] = recommendations[:10]  # type: ignore[assignment]  # Top 10 recommendations

    return json.dumps(analysis_result, ensure_ascii=False, indent=2)
