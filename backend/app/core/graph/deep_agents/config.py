"""Node configuration resolution — pure data extraction, no side effects.

Reads raw GraphNode data and produces typed config dataclasses.
Does NOT resolve models, tools, skills, or middleware — those are
handled by dedicated resolvers during the build phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.models.graph import GraphNode


@dataclass
class NodeConfig:
    """Resolved configuration for an agent node."""

    node_id: str
    name: str
    label: str
    node_type: str  # "agent", "code_agent", "a2a_agent"
    description: str

    # LLM
    model_name: Optional[str] = None
    provider_name: Optional[str] = None
    system_prompt: Optional[str] = None

    # Tools & Skills
    tool_names: List[Any] = field(default_factory=list)
    skill_ids: List[Any] = field(default_factory=list)

    # Memory
    enable_memory: bool = False
    memory_model_name: Optional[str] = None
    memory_provider_name: Optional[str] = None
    memory_prompt: Optional[str] = None

    # DeepAgents
    use_deep_agents: bool = False

    # A2A
    a2a_url: Optional[str] = None
    agent_card_url: Optional[str] = None
    a2a_auth_headers: Optional[Dict[str, str]] = None

    # Code Agent specific
    agent_mode: str = "autonomous"
    executor_type: str = "local"
    enable_data_analysis: bool = True
    additional_imports: List[str] = field(default_factory=list)
    docker_image: str = "python:3.11-slim"
    max_steps: int = 20
    enable_planning: bool = False

    # Raw config for passthrough
    raw_config: Dict[str, Any] = field(default_factory=dict)

    @property
    def display_name(self) -> str:
        """Human-readable node name for error messages and logs."""
        return self.label or self.name


def resolve_node_config(node: GraphNode, node_name: str) -> NodeConfig:
    """Extract typed config from a GraphNode. Pure function, no side effects."""
    data = node.data or {}
    config = data.get("config", {}) or {}
    node_type = data.get("type") or node.type or "agent"
    label = data.get("label", "") or ""

    return NodeConfig(
        node_id=str(node.id),
        name=node_name,
        label=label,
        node_type=node_type,
        description=config.get("description", "") or "",
        # LLM
        # LLM — prefer new split fields, fallback to legacy combined "model" field
        model_name=config.get("model_name") or config.get("model"),
        provider_name=config.get("provider_name") or config.get("provider"),
        system_prompt=config.get("systemPrompt") or config.get("system_prompt"),
        # Tools & Skills
        tool_names=config.get("tools") or [],
        skill_ids=config.get("skills") or [],
        # Memory — prefer new split fields, fallback to legacy camelCase
        enable_memory=bool(config.get("enableMemory", False)),
        memory_model_name=config.get("memory_model_name") or config.get("memoryModel"),
        memory_provider_name=config.get("memory_provider_name") or config.get("memoryProvider"),
        memory_prompt=config.get("memoryPrompt"),
        # DeepAgents
        use_deep_agents=bool(config.get("useDeepAgents", False)),
        # A2A
        a2a_url=config.get("a2a_url"),
        agent_card_url=config.get("agent_card_url"),
        a2a_auth_headers=config.get("a2a_auth_headers"),
        # Code Agent
        agent_mode=config.get("agent_mode", "autonomous"),
        executor_type=config.get("executor_type", "local"),
        enable_data_analysis=bool(config.get("enable_data_analysis", True)),
        additional_imports=config.get("additional_imports") or [],
        docker_image=config.get("docker_image", "python:3.11-slim"),
        max_steps=int(config.get("max_steps", 20)),
        enable_planning=bool(config.get("enable_planning", False)),
        raw_config=config,
    )


def resolve_all_configs(
    nodes: list[GraphNode],
    edges: list,
) -> tuple[Optional[NodeConfig], list[NodeConfig]]:
    """Resolve configs for all nodes. Returns (root_config, child_configs).

    Root is the node with no incoming edges (or the one with useDeepAgents=True).
    """
    # Build incoming edge map
    target_ids = {edge.target_node_id for edge in edges}

    # Find root nodes (no incoming edges)
    root_nodes = [n for n in nodes if n.id not in target_ids]

    if not root_nodes:
        return None, []

    # Select root: prefer the one with useDeepAgents, else first
    root_node = root_nodes[0]
    for n in root_nodes:
        data = n.data or {}
        config = data.get("config", {}) or {}
        if config.get("useDeepAgents", False):
            root_node = n
            break

    # Build name map
    node_id_to_name: dict[str, str] = {}
    for n in nodes:
        data = n.data or {}
        label = data.get("label", "")
        if label:
            name = str(label).lower().replace(" ", "_").replace("-", "_")
        else:
            node_type = data.get("type") or n.type or "agent"
            name = f"{node_type}_{str(n.id)[:8]}"
        node_id_to_name[str(n.id)] = name

    # Resolve root config
    root_config = resolve_node_config(root_node, node_id_to_name[str(root_node.id)])

    # Find children (nodes connected from root via edges)
    child_ids = {edge.target_node_id for edge in edges if edge.source_node_id == root_node.id}
    child_nodes = [n for n in nodes if n.id in child_ids]

    child_configs = [resolve_node_config(n, node_id_to_name[str(n.id)]) for n in child_nodes]

    return root_config, child_configs
