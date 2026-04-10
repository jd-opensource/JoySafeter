"""DeepAgents builder — orchestrates the complete build pipeline.

Two-level star structure: Root (Manager) → Children (Workers).
No inheritance — uses composition of dedicated resolvers.
"""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional

from loguru import logger

from app.common.exceptions import AppException
from app.core.agent.backends.constants import DOCKER_UNAVAILABLE_MSG
from app.core.agent.backends.docker_check import is_docker_available
from app.core.graph.deep_agents.agent_factory import (
    build_a2a_worker,
    build_code_agent_worker,
    build_standard_worker,
)
from app.core.graph.deep_agents.config import NodeConfig, resolve_all_configs
from app.core.graph.deep_agents.middleware import resolve_memory_middleware
from app.core.graph.deep_agents.model_resolver import ModelResolver
from app.core.graph.deep_agents.skills_loader import (
    has_valid_skills,
    preload_skills,
    resolve_skill_ids,
)
from app.core.graph.deep_agents.tool_resolver import resolve_tools
from app.core.graph.runtime_prompt_template import build_runtime_prompt_context, render_runtime_template
from app.models.graph import AgentGraph, GraphEdge, GraphNode

LOG_PREFIX = "[DeepAgentsBuilder]"


async def build_deep_agents_graph(
    graph: AgentGraph,
    nodes: List[GraphNode],
    edges: List[GraphEdge],
    user_id: Optional[Any] = None,
    model_service: Optional[Any] = None,
    thread_id: Optional[str] = None,
    file_emitter: Optional[Any] = None,
) -> Any:
    """Build a DeepAgents graph. Main entry point.

    Pipeline:
    1. Resolve configs (pure, no side effects)
    2. Setup shared backend if needed
    3. Preload skills
    4. Resolve models, tools, middleware per node
    5. Build agents
    6. Compile and finalize
    """
    if not nodes:
        raise ValueError("No nodes provided for DeepAgents graph")

    # --- 1. Resolve configs ---
    root_config, child_configs = resolve_all_configs(nodes, edges)
    if not root_config:
        raise ValueError("No root node found")
    if not root_config.use_deep_agents:
        raise ValueError("Root node must have DeepAgents enabled")

    logger.info(f"{LOG_PREFIX} Building graph: root='{root_config.name}', children={len(child_configs)}")

    # --- 2. Setup shared backend ---
    backend = None
    sandbox_handle = None
    all_configs = [root_config] + child_configs
    hard_docker = _any_requires_docker(all_configs)
    soft_docker = _any_wants_docker(all_configs)

    if (hard_docker or soft_docker) and user_id:
        docker_ok = await asyncio.to_thread(is_docker_available)

        if not docker_ok and hard_docker:
            raise AppException(status_code=503, message=DOCKER_UNAVAILABLE_MSG)

        if docker_ok:
            sandbox_handle = await _get_user_sandbox(user_id)
            backend = sandbox_handle.adapter
            if backend and file_emitter:
                from app.core.agent.backends.file_tracking_proxy import FileTrackingProxy

                backend = FileTrackingProxy(backend, file_emitter)
        elif soft_docker:
            # Docker wanted but not required — degrade gracefully
            logger.warning(
                f"{LOG_PREFIX} Docker is not available. "
                f"Skipping skills preloading; agent will continue without sandbox."
            )

    try:
        # --- 3. Preload skills (deduplicated across nodes) ---
        if backend:
            seen_skill_keys: set[frozenset[str]] = set()
            for cfg in all_configs:
                if has_valid_skills(cfg.skill_ids):
                    key = frozenset(cfg.skill_ids)
                    if key in seen_skill_keys:
                        continue
                    seen_skill_keys.add(key)
                    skill_uuids = await resolve_skill_ids(cfg.skill_ids, str(user_id))
                    await preload_skills(skill_uuids, backend, str(user_id))

        # --- 4. Create model resolver ---
        model_resolver = ModelResolver(
            model_service=model_service,
            user_id=str(user_id) if user_id else None,
        )

        # Runtime prompt context
        prompt_context = build_runtime_prompt_context(graph, user_id=user_id, thread_id=thread_id)

        # --- 5. Build workers ---
        subagents = []
        for cfg in child_configs:
            agent = await _build_worker(cfg, model_resolver, backend, str(user_id), prompt_context)
            subagents.append(agent)

        # --- 6. Build root ---
        root_model = await model_resolver.resolve(root_config.model_name, root_config.provider_name)
        root_tools = await resolve_tools(root_config.tool_names, str(user_id))
        root_middleware = await resolve_memory_middleware(
            root_config.enable_memory,
            root_config.memory_model_name,
            root_config.memory_prompt,
            model_resolver,
            str(user_id),
            str(graph.id),
        )

        root_prompt = root_config.system_prompt
        if root_prompt and prompt_context:
            root_prompt = render_runtime_template(root_prompt, prompt_context)

        # Create root DeepAgent
        from deepagents import create_deep_agent

        from app.core.agent.checkpointer.checkpointer import get_checkpointer

        root_agent = create_deep_agent(
            model=root_model,
            system_prompt=root_prompt,
            tools=root_tools,
            subagents=subagents,
            middleware=root_middleware,
            name=root_config.name,
            backend=backend,
            checkpointer=get_checkpointer(),
        )

        # --- 7. Finalize ---
        compiled = _finalize(root_agent, backend, sandbox_handle)
        # Attach sandbox handle to compiled graph so the caller can release it
        if sandbox_handle:
            compiled._sandbox_handle = sandbox_handle  # type: ignore[attr-defined]
        logger.info(f"{LOG_PREFIX} Build complete")
        return compiled

    except Exception:
        if sandbox_handle:
            await _cleanup_backend(sandbox_handle)
        raise


# ---------------------------------------------------------------------------
# Worker builder
# ---------------------------------------------------------------------------


async def _build_worker(
    cfg: NodeConfig,
    model_resolver: ModelResolver,
    backend: Any,
    user_id: str,
    prompt_context: dict,
) -> Any:
    """Build a single worker agent from its config."""
    if not cfg.description:
        cfg.description = f"Specialized worker: {cfg.label or cfg.name}"

    if cfg.system_prompt and prompt_context:
        cfg.system_prompt = render_runtime_template(cfg.system_prompt, prompt_context)

    if cfg.node_type == "a2a_agent":
        return await build_a2a_worker(cfg)

    # Resolve model and tools
    model = await model_resolver.resolve(cfg.model_name, cfg.provider_name)
    tools = await resolve_tools(cfg.tool_names, user_id)

    if cfg.node_type == "code_agent":
        return build_code_agent_worker(cfg, model, tools, backend)

    # Standard agent worker
    middleware = await resolve_memory_middleware(
        cfg.enable_memory,
        cfg.memory_model_name,
        cfg.memory_prompt,
        model_resolver,
        user_id,
    )
    return build_standard_worker(cfg, model, tools, middleware)


# ---------------------------------------------------------------------------
# Finalization
# ---------------------------------------------------------------------------


def _finalize(agent: Any, backend: Any, sandbox_handle: Any = None) -> Any:
    """Attach backend cleanup and artifact export to the compiled agent."""
    if sandbox_handle:

        async def cleanup():
            await _cleanup_backend(sandbox_handle)

        agent._cleanup_backend = cleanup

    if backend:
        from app.core.agent.backends.pydantic_adapter import PydanticSandboxAdapter

        if isinstance(backend, PydanticSandboxAdapter):
            agent._export_artifacts_to = backend.export_working_dir_to

    return agent


# ---------------------------------------------------------------------------
# Backend management
# ---------------------------------------------------------------------------


def _any_requires_docker(configs: List[NodeConfig]) -> bool:
    """Check if any node REQUIRES Docker (hard dependency).

    Only ``code_agent`` with explicit ``executor_type="docker"`` truly requires
    Docker — the agent literally executes code inside the container and has no
    local fallback.
    """
    for cfg in configs:
        if cfg.node_type == "code_agent" and cfg.executor_type == "docker":
            return True
    return False


def _any_wants_docker(configs: List[NodeConfig]) -> bool:
    """Check if any node WANTS Docker (soft dependency, can degrade gracefully).

    Skills preloading and ``code_agent`` with ``executor_type="auto"`` benefit
    from Docker but can fall back to running without it (skills are skipped,
    code_agent uses LocalPythonExecutor).
    """
    for cfg in configs:
        if has_valid_skills(cfg.skill_ids):
            return True
        if cfg.node_type == "code_agent" and cfg.executor_type == "auto":
            return True
    return False


async def _get_user_sandbox(user_id: Any) -> Any:
    """Get user's shared sandbox handle from pool.

    Returns a SandboxHandle. The caller MUST call handle.release() when done,
    or use it as an async context manager.
    """
    from app.services.sandbox_manager import get_sandbox_handle

    handle = await get_sandbox_handle(str(user_id))
    logger.info(f"{LOG_PREFIX} Got sandbox handle: sandbox_id={handle.sandbox_id}, user={user_id}")
    return handle


async def _cleanup_backend(backend: Any) -> None:
    """Release sandbox handle reference."""
    from app.services.sandbox_handle import SandboxHandle

    if isinstance(backend, SandboxHandle):
        await backend.release()
        return

    # Fallback for bare adapters (legacy path)
    sandbox_id = getattr(backend, "id", None)
    if sandbox_id:
        try:
            from app.services.sandbox_manager import _sandbox_pool

            await _sandbox_pool.release(sandbox_id)
        except Exception as e:
            logger.warning(f"{LOG_PREFIX} Pool release failed: {e}")
