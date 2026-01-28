"""
Schemas for DeepAgents Copilot artifacts.

Blueprint 结构对齐 ReactFlow 节点/边格式，确保与前端 executeGraphActions 兼容。

所有产物落盘路径：
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
    """需求分析产物 - /analysis.json"""

    goal: str = Field(..., description="用户的核心目标")
    complexity: ComplexityLevel = Field(default="moderate", description="复杂度级别")
    mode: OperationMode = Field(default="create", description="操作模式: create=创建新图, update=更新现有图")
    target_nodes: Optional[List[str]] = Field(default=None, description="更新模式下需要修改的目标节点 ID 列表")
    use_deep_agents: bool = Field(default=False, description="是否需要 DeepAgents 模式")
    patterns: List[str] = Field(default_factory=list, description="识别到的流程模式")
    clarifications: List[str] = Field(default_factory=list, description="需要澄清的问题")
    node_count_estimate: int = Field(default=3, description="预估节点数量")
    confidence: float = Field(default=0.7, ge=0, le=1, description="分析置信度")


# ==================== Blueprint (Stage 2) ====================
# 结构对齐 ReactFlow 节点/边格式


class NodePosition(BaseModel):
    """节点位置 - 对应 ReactFlow node.position"""

    x: float
    y: float


class NodeConfig(BaseModel):
    """节点配置 - 对应 ReactFlow node.data.config"""

    systemPrompt: Optional[str] = Field(default=None, description="系统提示词（agent 必填）")
    description: Optional[str] = Field(default=None, description="节点描述（DeepAgents 子代理必填）")
    useDeepAgents: Optional[bool] = Field(default=None, description="启用 DeepAgents 模式")
    model: Optional[str] = Field(default=None, description="模型名称")
    tools: Optional[Dict[str, List[str]]] = Field(default=None, description="工具配置 {builtin:[], mcp:[]}")
    expression: Optional[str] = Field(default=None, description="条件表达式（condition 节点）")
    instruction: Optional[str] = Field(default=None, description="路由指令（condition_agent 节点）")
    options: Optional[List[str]] = Field(default=None, description="路由选项（condition_agent 节点）")
    template: Optional[str] = Field(default=None, description="回复模板（direct_reply 节点）")
    prompt: Optional[str] = Field(default=None, description="人工输入提示（human_input 节点）")


class BlueprintNode(BaseModel):
    """Blueprint 节点 - 对齐 ReactFlow 节点结构"""

    id: str = Field(..., description="唯一节点 ID")
    type: str = Field(..., description="节点类型: agent, condition, condition_agent, direct_reply, human_input")
    label: str = Field(..., description="节点显示名称")
    position: NodePosition = Field(..., description="节点位置")
    config: NodeConfig = Field(default_factory=NodeConfig, description="节点配置")


class BlueprintEdge(BaseModel):
    """Blueprint 边 - 对齐 ReactFlow 边结构"""

    source: str = Field(..., description="源节点 ID")
    target: str = Field(..., description="目标节点 ID")
    label: Optional[str] = Field(default=None, description="边标签（可选）")
    condition: Optional[str] = Field(default=None, description="条件表达式（条件边）")


class WorkflowBlueprint(BaseModel):
    """工作流蓝图 - /blueprint.json"""

    name: str = Field(..., description="工作流名称")
    description: str = Field(..., description="工作流描述")
    nodes: List[BlueprintNode] = Field(default_factory=list, description="节点列表")
    edges: List[BlueprintEdge] = Field(default_factory=list, description="边列表")


# ==================== Validation (Stage 3) ====================


class ValidationIssue(BaseModel):
    """验证问题"""

    type: str = Field(..., description="问题类型: missing_field, orphan_node, dead_end, weak_prompt")
    severity: Literal["error", "warning", "info"] = Field(default="warning", description="严重程度")
    message: str = Field(..., description="问题描述")
    node_id: Optional[str] = Field(default=None, description="相关节点 ID")


class ValidationReport(BaseModel):
    """验证报告 - /validation.json"""

    is_valid: bool = Field(..., description="是否通过验证")
    health_score: int = Field(default=80, ge=0, le=100, description="健康分数")
    issues: List[ValidationIssue] = Field(default_factory=list, description="问题列表")
    recommendations: List[str] = Field(default_factory=list, description="改进建议")


# ==================== Run Index ====================


class CopilotDeepagentsIndex(BaseModel):
    """运行索引 - /index.json"""

    graph_id: Optional[str] = None
    run_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    model: Optional[str] = None
    user_id: Optional[str] = None
    actions_count: int = 0
    health_score: Optional[int] = None
    ok: bool = True
    notes: Optional[str] = None
