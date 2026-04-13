"""
DeepAgents Copilot Manager.

Use the DeepAgents Manager + sub-agent pattern to generate arbitrary graph types:
- Manager: orchestrate sub-agents, call create_node/connect_nodes tools to output GraphActions
- Sub-agents: plan/design/validate, producing artifact files
- Final output: standard GraphActions (fully compatible with existing Copilot)
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, List, Optional, Type

if TYPE_CHECKING:
    from deepagents import SubAgent as SubAgentT
    from deepagents.backends.filesystem import FilesystemBackend as FilesystemBackendT

from langchain_core.runnables import Runnable
from loguru import logger

from app.core.copilot.tools import connect_nodes, create_node, delete_node, update_config

from .artifacts import ArtifactStore
from .prompts import (
    MANAGER_SYSTEM_PROMPT,
    REQUIREMENTS_ANALYST_PROMPT,
    VALIDATOR_PROMPT,
    WORKFLOW_ARCHITECT_PROMPT,
)

# ==================== Optional deepagents imports ====================
# declare as optional first to avoid assigning None in except block (mypy "Cannot assign to a type")
create_deep_agent: Any = None
FilesystemMiddleware: Type[Any] | None = None
FilesystemBackend: Type[Any] | None = None
SubAgent: Type[Any] | None = None
DEEPAGENTS_AVAILABLE = False

try:
    from deepagents import (
        FilesystemMiddleware as _FilesystemMiddleware,
    )
    from deepagents import (
        SubAgent as _SubAgent,
    )
    from deepagents import (
        create_deep_agent as _create_deep_agent,
    )
    from deepagents.backends.filesystem import FilesystemBackend as _FilesystemBackend

    create_deep_agent = _create_deep_agent
    FilesystemMiddleware = _FilesystemMiddleware
    FilesystemBackend = _FilesystemBackend
    SubAgent = _SubAgent
    DEEPAGENTS_AVAILABLE = True
except ImportError:
    logger.warning("[DeepAgentsCopilot] deepagents library not available")

# ==================== Manager Factory ====================


def get_artifacts_root() -> Path:
    """Return the artifacts root directory."""
    root = os.environ.get("DEEPAGENTS_ARTIFACTS_DIR", "")
    if not root:
        root = str(Path.home() / ".agent-platform" / "deepagents")
    return Path(root)


def _build_subagents(backend: "FilesystemBackendT") -> List["SubAgentT"]:
    """
    Build the sub-agent list.

    Each sub-agent only has filesystem tools (read/write files); they do not call Copilot tools.

    SubAgent description best practices (per DeepAgents docs):
    - specific, action-oriented
    - describe "what it does" not "what it is"
    - help the Manager select the right sub-agent

    Reference: https://docs.langchain.com/oss/python/deepagents/subagents
    """
    return [
        {
            "name": "requirements-analyst",
            "description": (
                "Analyze the user's agent workflow request and output a structured requirements spec. "
                "Used for: 1) determining whether to create a new graph or update an existing one; "
                "2) assessing complexity level; "
                "3) deciding whether DeepAgents multi-agent collaboration is needed. "
                "Outputs /analysis.json containing fields such as goal, mode, complexity, use_deep_agents."
            ),
            "system_prompt": REQUIREMENTS_ANALYST_PROMPT,
            "tools": [],  # filesystem tools provided via middleware
        },
        {
            "name": "workflow-architect",
            "description": (
                "Design the complete architecture of an agent workflow based on requirements analysis. "
                "Used for: 1) designing node structure and connection relationships; "
                "2) writing professional systemPrompts for each agent; "
                "3) configuring DeepAgents hierarchy (Manager + sub-agents). "
                "Outputs /blueprint.json in ReactFlow-compatible format containing nodes and edges. "
                "Also used to fix validation issues by reading the existing blueprint and making targeted modifications."
            ),
            "system_prompt": WORKFLOW_ARCHITECT_PROMPT,
            "tools": [],
        },
        {
            "name": "validator",
            "description": (
                "Validate the structural integrity and quality of the workflow blueprint. "
                "Used for: 1) checking required fields and data formats; "
                "2) verifying DeepAgents rules (description, hierarchy constraints); "
                "3) assessing systemPrompt quality; "
                "4) detecting topology issues (orphan nodes, invalid edges). "
                "Outputs /validation.json containing is_valid, health_score, and an issues list."
            ),
            "system_prompt": VALIDATOR_PROMPT,
            "tools": [],
        },
    ]


def create_copilot_manager(
    *,
    model: Any,
    graph_id: Optional[str] = None,
    run_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> tuple[Runnable, ArtifactStore]:
    """
    Create a DeepAgents Copilot Manager.

    Args:
        model: Pre-created LangChain model instance (from ModelResolver)
        graph_id: Graph ID for artifact storage
        run_id: Optional run ID (auto-generated if not provided)
        user_id: User ID for workspace isolation

    Returns:
        (manager_agent, artifact_store)
    """
    if not DEEPAGENTS_AVAILABLE or create_deep_agent is None or FilesystemBackend is None:
        raise RuntimeError("deepagents library not available. Install with: pip install deepagents")
    assert create_deep_agent is not None and FilesystemBackend is not None  # narrow types for mypy

    # generate run_id
    if not run_id:
        run_id = f"run_{uuid.uuid4().hex[:12]}"

    # create artifact store
    artifacts_root = get_artifacts_root()
    graph_dir = graph_id or "unknown_graph"
    run_dir = artifacts_root / graph_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    store = ArtifactStore(
        graph_id=graph_id,
        run_id=run_id,
        run_dir=run_dir,
    )

    # create filesystem backend (for sub-agent file I/O)
    backend = FilesystemBackend(root_dir=run_dir)

    # Copilot tools (Manager uses these to generate GraphActions)
    copilot_tools = [
        create_node,
        connect_nodes,
        delete_node,
        update_config,
    ]

    # sub-agent configuration
    subagent_specs = _build_subagents(backend)

    # FilesystemMiddleware gives both Agent and sub-agents filesystem tools
    # DeepAgents already includes FilesystemMiddleware

    # create DeepAgents Manager
    manager = create_deep_agent(
        model=model,
        system_prompt=MANAGER_SYSTEM_PROMPT,
        tools=copilot_tools,
        subagents=subagent_specs,
        name="copilot-deepagents-manager",
    )

    logger.info(f"[DeepAgentsCopilot] Created manager run_id={run_id} run_dir={run_dir}")

    return manager, store


# ==================== Schema Validation Helpers (Moved to .utils) ====================

# Re-exporting from .utils if needed, but better to import directly from .utils

# ==================== Helpers (Moved to .utils) ====================
