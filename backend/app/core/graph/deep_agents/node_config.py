"""Unified agent configuration resolver - for both Manager and SubAgent."""

from dataclasses import dataclass
from typing import Any, Optional

from loguru import logger

from app.models.graph import GraphNode

LOG_PREFIX = "[AgentConfig]"


@dataclass
class AgentConfig:
    """Unified agent configuration - works for both Manager and SubAgent."""

    name: str
    label: str
    node_type: str
    description: Optional[str]
    system_prompt: Optional[str]
    model: Any
    tools: list[Any]
    middleware: list[Any]
    skills: Optional[list[str]]
    backend: Optional[Any]

    @classmethod
    async def from_node(
        cls,
        node: GraphNode,
        builder: Any,  # DeepAgentsGraphBuilder
        node_id_to_name: dict,
        default_description: Optional[str] = None,
    ) -> "AgentConfig":
        """Parse and resolve all node properties into unified config.

        Args:
            node: GraphNode to parse
            builder: DeepAgentsGraphBuilder instance
            node_id_to_name: Mapping of node IDs to names
            default_description: Default description if not in config
        """
        from app.core.agent.node_tools import resolve_tools_for_node

        data = node.data or {}
        config = data.get("config", {})
        label = data.get("label", "")
        node_type = data.get("type", "agent")

        # Name resolution
        name = label or node_id_to_name.get(node.id) or builder._get_node_name(node)
        node_id_to_name[node.id] = name
        # Note: _get_node_name is from BaseGraphBuilder, acceptable to use

        # Tools resolution
        raw_tools = await resolve_tools_for_node(node, user_id=builder.user_id)
        tools = await builder._resolve_tools_from_registry(raw_tools, user_id=builder.user_id)

        # Skills resolution
        skill_ids_raw = config.get("skills")
        has_skills = builder.has_valid_skills_config(skill_ids_raw)

        # Backend resolution
        backend = await builder.get_backend_for_node(node, has_skills)

        # Preload skills if needed
        if backend and has_skills:
            await builder.preload_skills_to_backend(node, backend)

        # Middleware resolution
        middleware = await builder.resolve_middleware_for_node_with_backend(node, backend, user_id=builder.user_id)

        # Skills paths - only set if both skills are configured AND backend is available
        # This ensures skills parameter is only passed to create_deep_agent when actually usable
        skills = builder.get_skills_paths(has_skills, backend)

        # Model resolution
        model = await builder._resolve_node_llm(node)

        # System prompt
        system_prompt = builder._get_system_prompt_from_node(node)

        # Description
        description = config.get("description") or default_description
        if not description:
            description = f"Agent: {label or name}"

        logger.debug(
            f"{LOG_PREFIX} Config for '{name}': "
            f"tools={len(tools) if tools else 0}, "
            f"middleware={len(middleware) if middleware else 0}, "
            f"skills={'enabled' if skills else 'disabled'}"
        )

        return cls(
            name=name,
            label=label,
            node_type=node_type,
            description=description,
            system_prompt=system_prompt,
            model=model,
            tools=tools,
            middleware=middleware,
            skills=skills,
            backend=backend,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format (for backward compatibility)."""
        return {
            "name": self.name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "model": self.model,
            "middleware": self.middleware,
            "skills": self.skills,
            "backend": self.backend,
        }


@dataclass
class CodeAgentConfig(AgentConfig):
    """Extended config for CodeAgent nodes with specialized properties."""

    agent_mode: str = "autonomous"
    executor_type: str = "local"
    enable_data_analysis: bool = True
    additional_imports: Optional[list[str]] = None
    docker_image: str = "python:3.11-slim"
    max_steps: int = 20
    enable_planning: bool = False

    def __post_init__(self):
        if self.additional_imports is None:
            self.additional_imports = []

    @classmethod
    async def from_node(
        cls,
        node: GraphNode,
        builder: Any,
        node_id_to_name: dict,
        default_description: Optional[str] = None,  # type: ignore[override]
    ) -> "CodeAgentConfig":
        """Parse CodeAgent node with all specialized properties."""
        # Get base config
        base_config = await AgentConfig.from_node(
            node, builder, node_id_to_name, default_description="Python code execution agent"
        )

        data = node.data or {}
        config = data.get("config", {})

        # Extract CodeAgent-specific properties
        agent_mode = config.get("agent_mode", "autonomous")
        executor_type = config.get("executor_type", "local")
        enable_data_analysis = config.get("enable_data_analysis", True)
        additional_imports = config.get("additional_imports", [])
        docker_image = config.get("docker_image", "python:3.11-slim")
        max_steps = config.get("max_steps", 20)
        enable_planning = config.get("enable_planning", False)

        # Override description with mode info if not provided
        description = config.get("description")
        if not description:
            description = f"Python code execution agent ({agent_mode} mode)"

        return cls(
            name=base_config.name,
            label=base_config.label,
            node_type=base_config.node_type,
            description=description,
            system_prompt=base_config.system_prompt,
            model=base_config.model,
            tools=base_config.tools,
            middleware=base_config.middleware,
            skills=base_config.skills,
            backend=base_config.backend,
            agent_mode=agent_mode,
            executor_type=executor_type,
            enable_data_analysis=enable_data_analysis,
            additional_imports=additional_imports,
            docker_image=docker_image,
            max_steps=max_steps,
            enable_planning=enable_planning,
        )
