"""
Multi-Stage Workflow Generator

Implements a sophisticated multi-stage approach for generating complex workflows:
1. ANALYZE: Understand user requirements and complexity
2. PLAN: Design workflow architecture
3. GENERATE: Create nodes and edges incrementally
4. VALIDATE: Check for errors and completeness
5. OPTIMIZE: Suggest improvements

This module enhances the Copilot's ability to generate professional-grade workflows.
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from loguru import logger


class ComplexityLevel(str, Enum):
    """Workflow complexity levels."""

    SIMPLE = "simple"  # 1-3 nodes, linear flow
    MODERATE = "moderate"  # 4-7 nodes, some branching
    COMPLEX = "complex"  # 8-15 nodes, multiple branches
    ADVANCED = "advanced"  # 15+ nodes, DeepAgents, nested flows


class WorkflowPattern(str, Enum):
    """Common workflow patterns."""

    LINEAR = "linear"  # A → B → C
    BRANCHING = "branching"  # A → [B, C] → D
    PARALLEL = "parallel"  # [A, B, C] → D
    LOOP = "loop"  # A → B → C → (condition) → [A / D]
    HIERARCHICAL = "hierarchical"  # Manager → [Workers]
    HYBRID = "hybrid"  # Combination of patterns


@dataclass
class RequirementAnalysis:
    """Analysis of user requirements."""

    original_request: str
    complexity: ComplexityLevel
    patterns: List[WorkflowPattern]
    key_entities: List[str]
    input_type: str
    output_type: str
    implicit_requirements: List[str]
    suggested_node_count: int
    use_deep_agents: bool
    confidence: float
    clarification_needed: List[str] = field(default_factory=list)


@dataclass
class WorkflowPlan:
    """Planned workflow structure before generation."""

    name: str
    description: str
    phases: List[Dict[str, Any]]
    nodes_spec: List[Dict[str, Any]]
    edges_spec: List[Dict[str, str]]
    estimated_complexity: ComplexityLevel
    deep_agents_structure: Optional[Dict[str, Any]] = None


@dataclass
class ValidationResult:
    """Result of workflow validation."""

    is_valid: bool
    errors: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    suggestions: List[str]
    health_score: int  # 0-100


class MultiStageGenerator:
    """
    Multi-stage workflow generator that implements:
    1. Requirement Analysis
    2. Architecture Planning
    3. Incremental Generation
    4. Validation
    5. Optimization
    """

    def __init__(self, graph_context: Dict[str, Any]):
        """
        Initialize generator with current graph context.

        Args:
            graph_context: Current graph state with nodes and edges
        """
        self.graph_context = graph_context
        self.nodes = graph_context.get("nodes", [])
        self.edges = graph_context.get("edges", [])

    def analyze_requirements(self, user_request: str) -> RequirementAnalysis:
        """
        Stage 1: Analyze user requirements.

        This method parses the user request to understand:
        - Complexity level
        - Workflow patterns needed
        - Key entities and concepts
        - Input/output types
        - Implicit requirements

        Args:
            user_request: User's natural language request

        Returns:
            RequirementAnalysis with parsed requirements
        """
        request_lower = user_request.lower()

        # Detect complexity indicators
        complexity_indicators = {
            ComplexityLevel.SIMPLE: ["simple", "basic", "just", "only", "单个", "简单"],
            ComplexityLevel.MODERATE: ["with", "and then", "after", "然后", "接着"],
            ComplexityLevel.COMPLEX: ["multiple", "several", "various", "多个", "多种"],
            ComplexityLevel.ADVANCED: ["complex", "sophisticated", "enterprise", "复杂", "专业"],
        }

        detected_complexity = ComplexityLevel.MODERATE
        for level, indicators in complexity_indicators.items():
            if any(ind in request_lower for ind in indicators):
                detected_complexity = level

        # Detect patterns
        patterns = []
        pattern_keywords = {
            WorkflowPattern.LINEAR: ["then", "next", "followed by", "然后", "接下来"],
            WorkflowPattern.BRANCHING: ["if", "decide", "route", "branch", "如果", "分支"],
            WorkflowPattern.PARALLEL: ["parallel", "concurrent", "at the same time", "并行"],
            WorkflowPattern.LOOP: ["repeat", "iterate", "loop", "retry", "循环", "重试"],
            WorkflowPattern.HIERARCHICAL: ["manager", "worker", "subagent", "coordinate", "主从"],
        }

        for pattern, keywords in pattern_keywords.items():
            if any(kw in request_lower for kw in keywords):
                patterns.append(pattern)

        if not patterns:
            patterns = [WorkflowPattern.LINEAR]

        # Check if DeepAgents is appropriate
        deep_agents_keywords = ["research", "complex", "multi-step", "analyze", "研究", "分析", "多步"]
        use_deep_agents = any(kw in request_lower for kw in deep_agents_keywords)

        # Estimate node count
        if detected_complexity == ComplexityLevel.SIMPLE:
            node_count = 2
        elif detected_complexity == ComplexityLevel.MODERATE:
            node_count = 4
        elif detected_complexity == ComplexityLevel.COMPLEX:
            node_count = 8
        else:
            node_count = 12

        # Extract key entities (simplified extraction)
        key_entities = []
        entity_markers = ["agent", "for", "to", "that", "用于", "来"]
        for marker in entity_markers:
            if marker in request_lower:
                idx = request_lower.find(marker)
                entity = request_lower[idx : idx + 50].split()[1:3]
                key_entities.extend(entity)

        # Determine if clarification is needed
        clarification_needed = []
        vague_indicators = ["something", "stuff", "thing", "it", "东西", "什么"]
        if any(vague in request_lower for vague in vague_indicators):
            clarification_needed.append("请具体说明您想要创建什么类型的工作流？")

        if len(request_lower) < 20:
            clarification_needed.append("请提供更多细节以便我创建更准确的工作流。")

        return RequirementAnalysis(
            original_request=user_request,
            complexity=detected_complexity,
            patterns=patterns,
            key_entities=key_entities[:5],
            input_type="user_message",
            output_type="processed_result",
            implicit_requirements=[],
            suggested_node_count=node_count,
            use_deep_agents=use_deep_agents,
            confidence=0.8 if not clarification_needed else 0.5,
            clarification_needed=clarification_needed,
        )

    def create_plan(self, analysis: RequirementAnalysis) -> WorkflowPlan:
        """
        Stage 2: Create workflow plan based on analysis.

        This generates a structured plan before creating actual nodes.

        Args:
            analysis: RequirementAnalysis from stage 1

        Returns:
            WorkflowPlan with planned structure
        """
        phases = []
        nodes_spec = []
        edges_spec = []

        # Determine phases based on patterns
        if WorkflowPattern.HIERARCHICAL in analysis.patterns or analysis.use_deep_agents:
            # DeepAgents structure
            phases = [
                {"name": "Coordination", "type": "manager", "description": "主协调节点"},
                {"name": "Execution", "type": "workers", "description": "执行子节点"},
                {"name": "Synthesis", "type": "aggregation", "description": "结果整合"},
            ]

            # Create manager node
            manager_id = f"agent_{uuid.uuid4().hex[:8]}"
            nodes_spec.append(
                {
                    "id": manager_id,
                    "type": "agent",
                    "label": "Coordinator",
                    "is_manager": True,
                    "use_deep_agents": True,
                    "description": "Coordinates subagents and synthesizes results",
                }
            )

            # Create worker nodes
            worker_count = min(analysis.suggested_node_count - 1, 4)
            for i in range(worker_count):
                worker_id = f"agent_{uuid.uuid4().hex[:8]}"
                nodes_spec.append(
                    {
                        "id": worker_id,
                        "type": "agent",
                        "label": f"Worker {i + 1}",
                        "is_worker": True,
                        "description": f"Specialized worker agent {i + 1}",
                    }
                )
                edges_spec.append({"source": manager_id, "target": worker_id})

        elif WorkflowPattern.BRANCHING in analysis.patterns:
            # Branching structure
            phases = [
                {"name": "Input Processing", "type": "preprocessing", "description": "输入处理"},
                {"name": "Decision", "type": "routing", "description": "决策分支"},
                {"name": "Branch Handling", "type": "parallel_branches", "description": "分支处理"},
                {"name": "Output", "type": "output", "description": "输出"},
            ]

            # Create preprocessing node
            preprocess_id = f"agent_{uuid.uuid4().hex[:8]}"
            nodes_spec.append(
                {
                    "id": preprocess_id,
                    "type": "agent",
                    "label": "Input Processor",
                }
            )

            # Create decision node
            decision_id = f"condition_agent_{uuid.uuid4().hex[:8]}"
            nodes_spec.append(
                {
                    "id": decision_id,
                    "type": "condition_agent",
                    "label": "Router",
                    "options": ["Branch A", "Branch B"],
                }
            )
            edges_spec.append({"source": preprocess_id, "target": decision_id})

            # Create branch nodes
            branch_a_id = f"agent_{uuid.uuid4().hex[:8]}"
            branch_b_id = f"agent_{uuid.uuid4().hex[:8]}"
            nodes_spec.append({"id": branch_a_id, "type": "agent", "label": "Branch A Handler"})
            nodes_spec.append({"id": branch_b_id, "type": "agent", "label": "Branch B Handler"})
            edges_spec.append({"source": decision_id, "target": branch_a_id})
            edges_spec.append({"source": decision_id, "target": branch_b_id})

        else:
            # Linear structure (default)
            phases = [
                {"name": "Input", "type": "entry", "description": "入口"},
                {"name": "Processing", "type": "processing", "description": "处理"},
                {"name": "Output", "type": "exit", "description": "出口"},
            ]

            # Create linear chain
            prev_id = None
            for i in range(analysis.suggested_node_count):
                node_id = f"agent_{uuid.uuid4().hex[:8]}"
                nodes_spec.append(
                    {
                        "id": node_id,
                        "type": "agent",
                        "label": f"Step {i + 1}",
                    }
                )
                if prev_id:
                    edges_spec.append({"source": prev_id, "target": node_id})
                prev_id = node_id

        return WorkflowPlan(
            name=f"Workflow for: {analysis.original_request[:50]}...",
            description=f"Auto-generated workflow with {len(nodes_spec)} nodes",
            phases=phases,
            nodes_spec=nodes_spec,
            edges_spec=edges_spec,
            estimated_complexity=analysis.complexity,
            deep_agents_structure={"use_deep_agents": analysis.use_deep_agents} if analysis.use_deep_agents else None,
        )

    def generate_actions(self, plan: WorkflowPlan, start_x: float = 100, start_y: float = 100) -> List[Dict[str, Any]]:
        """
        Stage 3: Generate actual actions from plan.

        Converts the plan into CREATE_NODE and CONNECT_NODES actions.

        Args:
            plan: WorkflowPlan from stage 2
            start_x: Starting X position
            start_y: Starting Y position

        Returns:
            List of action dictionaries
        """
        actions = []
        x_spacing = 300
        y_spacing = 150

        # Create nodes with proper positioning
        for i, node_spec in enumerate(plan.nodes_spec):
            # Calculate position based on node type and index
            if node_spec.get("is_manager"):
                pos_x = start_x
                pos_y = start_y
            elif node_spec.get("is_worker"):
                worker_index = sum(1 for n in plan.nodes_spec[:i] if n.get("is_worker"))
                pos_x = start_x + x_spacing
                pos_y = start_y + worker_index * y_spacing
            else:
                pos_x = start_x + i * x_spacing
                pos_y = start_y

            # Build config
            config: Dict[str, Any] = {}
            if node_spec["type"] == "agent":
                config["systemPrompt"] = f"You are a specialized agent for: {node_spec['label']}"
                if node_spec.get("use_deep_agents"):
                    config["useDeepAgents"] = True
                if node_spec.get("description"):
                    config["description"] = node_spec["description"]
            elif node_spec["type"] == "condition_agent":
                config["instruction"] = "Decide which branch to route to based on the input"
                config["options"] = node_spec.get("options", ["Option A", "Option B"])

            action = {
                "type": "CREATE_NODE",
                "payload": {
                    "id": node_spec["id"],
                    "type": node_spec["type"],
                    "label": node_spec["label"],
                    "position": {"x": pos_x, "y": pos_y},
                    "config": config,
                },
                "reasoning": f"Creating {node_spec['label']} as part of planned workflow",
            }
            actions.append(action)

        # Create edges
        for edge_spec in plan.edges_spec:
            action = {
                "type": "CONNECT_NODES",
                "payload": {
                    "source": edge_spec["source"],
                    "target": edge_spec["target"],
                },
                "reasoning": "Connecting planned workflow nodes",
            }
            actions.append(action)

        return actions

    def validate(self, nodes: List[Dict], edges: List[Dict]) -> ValidationResult:
        """
        Stage 4: Validate the generated workflow.

        Checks for structural issues, missing configurations, etc.

        Args:
            nodes: List of node dictionaries
            edges: List of edge dictionaries

        Returns:
            ValidationResult with issues and suggestions
        """
        errors = []
        warnings = []
        suggestions = []

        # Build adjacency structures
        {n.get("id") for n in nodes}
        outgoing: Dict[str, List[str]] = {str(n.get("id")): [] for n in nodes if n.get("id") is not None}
        incoming: Dict[str, List[str]] = {str(n.get("id")): [] for n in nodes if n.get("id") is not None}

        for edge in edges:
            src = edge.get("source") or edge.get("payload", {}).get("source")
            tgt = edge.get("target") or edge.get("payload", {}).get("target")
            if src in outgoing and tgt in incoming:
                outgoing[src].append(tgt)
                incoming[tgt].append(src)

        # Check 1: Orphan nodes
        for node in nodes:
            node_id = node.get("id") or node.get("payload", {}).get("id")
            if not incoming.get(node_id) and not outgoing.get(node_id) and len(nodes) > 1:
                errors.append(
                    {
                        "type": "orphan_node",
                        "node_id": node_id,
                        "message": "Node is not connected to any other node",
                    }
                )

        # Check 2: Dead ends
        for node in nodes:
            node_id = node.get("id") or node.get("payload", {}).get("id")
            node_type = node.get("type") or node.get("payload", {}).get("type", "")
            if not outgoing.get(node_id) and node_type not in ["direct_reply", "human_input"]:
                if len(nodes) > 1:  # Only warn if not single node
                    warnings.append(
                        {
                            "type": "dead_end",
                            "node_id": node_id,
                            "message": "Node has no outgoing edges",
                        }
                    )

        # Check 3: Missing systemPrompts for agents
        for node in nodes:
            node_type = node.get("type") or node.get("payload", {}).get("type", "")
            config = node.get("config") or node.get("payload", {}).get("config", {})
            if node_type == "agent":
                prompt = config.get("systemPrompt", "")
                if not prompt or len(prompt) < 20:
                    warnings.append(
                        {
                            "type": "weak_prompt",
                            "node_id": node.get("id") or node.get("payload", {}).get("id"),
                            "message": "Agent has weak or missing systemPrompt",
                        }
                    )
                    suggestions.append("Add detailed systemPrompts to agent nodes for better results")

        # Check 4: DeepAgents without children
        for node in nodes:
            node_id = node.get("id") or node.get("payload", {}).get("id")
            config = node.get("config") or node.get("payload", {}).get("config", {})
            if config.get("useDeepAgents"):
                children = outgoing.get(node_id, [])
                if not children:
                    errors.append(
                        {
                            "type": "deep_agent_no_children",
                            "node_id": node_id,
                            "message": "DeepAgent has no subagent children",
                        }
                    )

        # Calculate health score
        error_count = len(errors)
        warning_count = len(warnings)
        health_score = max(0, 100 - error_count * 25 - warning_count * 10)

        is_valid = error_count == 0

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
            health_score=health_score,
        )

    def optimize_suggestions(self, validation: ValidationResult) -> List[str]:
        """
        Stage 5: Generate optimization suggestions.

        Based on validation results, suggest improvements.

        Args:
            validation: ValidationResult from stage 4

        Returns:
            List of optimization suggestions
        """
        suggestions = list(validation.suggestions)

        if validation.health_score < 70:
            suggestions.append("Consider simplifying the workflow structure")

        if any(e.get("type") == "orphan_node" for e in validation.errors):
            suggestions.append("Connect all nodes to create a cohesive workflow")

        if any(w.get("type") == "weak_prompt" for w in validation.warnings):
            suggestions.append("Enhance systemPrompts with specific instructions, output formats, and constraints")

        return suggestions


def multi_stage_generate(
    user_request: str,
    graph_context: Dict[str, Any],
    start_x: float = 100,
    start_y: float = 100,
) -> Dict[str, Any]:
    """
    Convenience function to run full multi-stage generation.

    Args:
        user_request: User's natural language request
        graph_context: Current graph context
        start_x: Starting X position
        start_y: Starting Y position

    Returns:
        Dict with analysis, plan, actions, and validation
    """
    generator = MultiStageGenerator(graph_context)

    # Stage 1: Analyze
    analysis = generator.analyze_requirements(user_request)
    logger.info(f"[MultiStageGenerator] Analysis: complexity={analysis.complexity}, patterns={analysis.patterns}")

    # Check if clarification is needed
    if analysis.clarification_needed:
        return {
            "needs_clarification": True,
            "clarification_questions": analysis.clarification_needed,
            "analysis": {
                "complexity": analysis.complexity.value,
                "confidence": analysis.confidence,
            },
            "actions": [],
        }

    # Stage 2: Plan
    plan = generator.create_plan(analysis)
    logger.info(f"[MultiStageGenerator] Plan: {len(plan.nodes_spec)} nodes, {len(plan.edges_spec)} edges")

    # Stage 3: Generate
    actions = generator.generate_actions(plan, start_x, start_y)
    logger.info(f"[MultiStageGenerator] Generated {len(actions)} actions")

    # Stage 4: Validate
    # Extract nodes from actions for validation
    generated_nodes = [a for a in actions if a.get("type") == "CREATE_NODE"]
    generated_edges = [a for a in actions if a.get("type") == "CONNECT_NODES"]
    validation = generator.validate(generated_nodes, generated_edges)
    logger.info(f"[MultiStageGenerator] Validation: valid={validation.is_valid}, score={validation.health_score}")

    # Stage 5: Optimize
    suggestions = generator.optimize_suggestions(validation)

    return {
        "needs_clarification": False,
        "analysis": {
            "complexity": analysis.complexity.value,
            "patterns": [p.value for p in analysis.patterns],
            "use_deep_agents": analysis.use_deep_agents,
            "suggested_node_count": analysis.suggested_node_count,
            "confidence": analysis.confidence,
        },
        "plan": {
            "name": plan.name,
            "description": plan.description,
            "phases": plan.phases,
            "node_count": len(plan.nodes_spec),
            "edge_count": len(plan.edges_spec),
        },
        "actions": actions,
        "validation": {
            "is_valid": validation.is_valid,
            "health_score": validation.health_score,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "suggestions": suggestions,
    }
