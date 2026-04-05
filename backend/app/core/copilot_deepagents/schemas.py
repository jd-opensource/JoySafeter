"""
Schemas for DeepAgents Copilot artifacts.

Blueprint structure aligns with ReactFlow node/edge format to ensure
compatibility with the frontend executeGraphActions.

All artifact paths:
  $DEEPAGENTS_ARTIFACTS_DIR/{graph_id}/{run_id}/
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# ==================== Analysis (Stage 1) ====================

ComplexityLevel = Literal["simple", "moderate", "complex", "advanced"]
OperationMode = Literal["create", "update"]


class RequirementSpec(BaseModel):
    """Requirement analysis artifact - /analysis.json"""

    goal: str = Field(..., description="core user goal")
    complexity: ComplexityLevel = Field(default="moderate", description="complexity level")
    mode: OperationMode = Field(default="create", description="operation mode: create=new graph, update=modify existing graph")
    target_nodes: Optional[List[str]] = Field(default=None, description="node IDs to modify in update mode")
    use_deep_agents: bool = Field(default=False, description="whether DeepAgents mode is needed")
    patterns: List[str] = Field(default_factory=list, description="identified workflow patterns")
    clarifications: List[str] = Field(default_factory=list, description="questions needing clarification")
    node_count_estimate: int = Field(default=3, description="estimated node count")
    confidence: float = Field(default=0.7, ge=0, le=1, description="analysis confidence")


# ==================== Blueprint (Stage 2) ====================
# structure aligned with ReactFlow node/edge format


class NodePosition(BaseModel):
    """Node position - corresponds to ReactFlow node.position"""

    x: float
    y: float


class NodeConfig(BaseModel):
    """Node configuration - corresponds to ReactFlow node.data.config"""

    systemPrompt: Optional[str] = Field(default=None, description="system prompt (required for agent nodes)")
    description: Optional[str] = Field(default=None, description="node description (required for DeepAgents sub-agents)")
    useDeepAgents: Optional[bool] = Field(default=None, description="enable DeepAgents mode")
    model: Optional[str] = Field(default=None, description="model name")
    tools: Optional[Dict[str, List[str]]] = Field(default=None, description="tool config {builtin:[], mcp:[]}")
    expression: Optional[str] = Field(default=None, description="condition expression (condition node)")
    instruction: Optional[str] = Field(default=None, description="routing instruction (condition_agent node)")
    options: Optional[List[str]] = Field(default=None, description="routing options (condition_agent node)")
    template: Optional[str] = Field(default=None, description="reply template (direct_reply node)")
    prompt: Optional[str] = Field(default=None, description="human input prompt (human_input node)")


class BlueprintNode(BaseModel):
    """Blueprint node - aligned with ReactFlow node structure."""

    id: str = Field(..., description="unique node ID")
    type: str = Field(..., description="node type: agent, condition, condition_agent, direct_reply, human_input")
    label: str = Field(..., description="node display name")
    position: NodePosition = Field(..., description="node position")
    config: NodeConfig = Field(default_factory=NodeConfig, description="node configuration")


class BlueprintEdge(BaseModel):
    """Blueprint edge - aligned with ReactFlow edge structure."""

    source: str = Field(..., description="source node ID")
    target: str = Field(..., description="target node ID")
    label: Optional[str] = Field(default=None, description="edge label (optional)")
    condition: Optional[str] = Field(default=None, description="condition expression (conditional edge)")


class WorkflowBlueprint(BaseModel):
    """Workflow blueprint - /blueprint.json"""

    name: str = Field(..., description="workflow name")
    description: str = Field(..., description="workflow description")
    nodes: List[BlueprintNode] = Field(default_factory=list, description="node list")
    edges: List[BlueprintEdge] = Field(default_factory=list, description="edge list")


# ==================== Validation (Stage 3) ====================


class ValidationIssue(BaseModel):
    """Validation issue."""

    type: str = Field(..., description="issue type: missing_field, orphan_node, dead_end, weak_prompt")
    severity: Literal["error", "warning", "info"] = Field(default="warning", description="severity level")
    message: str = Field(..., description="issue description")
    node_id: Optional[str] = Field(default=None, description="related node ID")


class ValidationReport(BaseModel):
    """Validation report - /validation.json"""

    is_valid: bool = Field(..., description="whether validation passed")
    health_score: int = Field(default=80, ge=0, le=100, description="health score")
    issues: List[ValidationIssue] = Field(default_factory=list, description="issue list")
    recommendations: List[str] = Field(default_factory=list, description="improvement recommendations")


# ==================== Run Index ====================


class CopilotDeepagentsIndex(BaseModel):
    """Run index - /index.json"""

    graph_id: Optional[str] = None
    run_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: Optional[str] = None
    user_id: Optional[str] = None
    actions_count: int = 0
    health_score: Optional[int] = None
    ok: bool = True
    notes: Optional[str] = None
