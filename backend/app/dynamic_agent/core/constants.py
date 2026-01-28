from enum import Enum
from typing import Set

MCP_TOOL_JOINER = "_"
DOCKER_HOST_IP = "DOCKER_HOST_IP"
DOCKER_HOST_PORT = "DOCKER_HOST_PORT"
LOCALHOST = "localhost"
DOCKER_RUN_USER = "DOCKER_RUN_USER"
DOCKER_RUN_GROUP = "DOCKER_RUN_GROUP"
DOCKER_RUN_CAPS = ["NET_ADMIN", "NET_RAW", "SYS_ADMIN"]

# CTF Knowledge paths for volume mounting
CTF_KNOWLEDGE_HOST_PATH = "CTF_KNOWLEDGE_HOST_PATH"  # Env var for host path
CTF_KNOWLEDGE_CONTAINER_PATH = "/opt/ctf/knowledge"  # Fixed container path

# Development mode: mount source code for hot-reload
DEV_MODE_ENV = "SECLENS_DEV_MODE"  # Set to '1' or 'true' to enable dev mode
ENGINE_HOST_PATH = "ENGINE_HOST_PATH"  # Env var for engine source path
AGENT_HOST_PATH = "AGENT_HOST_PATH"  # Env var for agent source path
ENGINE_CONTAINER_PATH = "/app/dynamic_engine"  # Fixed container path for engine
AGENT_CONTAINER_PATH = "/app/app"  # Fixed container path for agent


THINK_TOOL_NAME = "think_tool"
AGENT_TOOL_NAME = "agent_tool"


# =============================================================================
# CTF Mode Constants
# =============================================================================


class CtfDetectionSource(str, Enum):
    """Source of CTF mode detection."""

    USER = "user"  # Explicitly set by user
    HEURISTIC = "heuristic"  # Auto-detected from keywords
    OVERRIDE = "override"  # Forced by system/admin


class CtfSessionStatus(str, Enum):
    """CTF session lifecycle status."""

    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    CLOSED = "closed"


class CtfToolType(str, Enum):
    """Tool types for CTF prioritization."""

    SHELL = "shell"
    PYTHON = "python"
    OTHER = "other"


class CtfRiskLevel(str, Enum):
    """Risk level for CTF actions."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CtfAttemptOutcome(str, Enum):
    """Outcome of a CTF attempt step."""

    SUCCESS = "success"
    NO_DATA = "no_data"
    ERROR = "error"


class CtfHintStatus(str, Enum):
    """Status of user-provided hints."""

    QUEUED = "queued"
    APPLIED = "applied"
    SKIPPED = "skipped"


class CtfReferenceSource(str, Enum):
    """Source of CTF reference hits."""

    LOCAL_BANK = "local_bank"
    PRIOR_SOLUTION = "prior_solution"
    HEURISTIC = "heuristic"


# CTF Intent Keywords - DEPRECATED
# Use is_ctf_context() from app.dynamic_agent.prompts.system_prompts instead
# This is kept only for backward compatibility
CTF_INTENT_KEYWORDS: Set[str] = {
    "flag{",
    "ctf{",
    "capture the flag",  # Minimal definite patterns only
}

# Prioritized tool types for CTF mode (shell/python first)
CTF_PRIORITY_TOOL_TYPES = [CtfToolType.SHELL, CtfToolType.PYTHON]

# Tool name patterns for CTF prioritization
CTF_SHELL_TOOL_PATTERNS = {"shell", "command", "bash", "sh", "terminal", "exec", "curl", "nc", "netcat"}
CTF_PYTHON_TOOL_PATTERNS = {"python", "script", "code", "eval", "coder"}

# T010: CTF preset MCP tools - skip tool discovery, use these directly
# Note: agent_tool.py adds 'seclens_' prefix when looking up these in MCP registry
# Non-MCP tools (knowledge_search, think_tool, etc.) are added separately in agent_tool.py
CTF_PRESET_TOOLS = [
    "execute_shell_command",
    "execute_python_script",
]
# Note: agent_tool is always included separately as it's the task decomposition tool
