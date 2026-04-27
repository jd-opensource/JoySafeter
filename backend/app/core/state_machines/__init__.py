"""Centralized state machine definitions and transition functions."""

from app.core.state_machines.definitions import (
    AGENT_STATES,
    AGENT_TERMINAL,
    EXECUTION_STATES,
    EXECUTION_TERMINAL,
    RELEASE_STATES,
    RELEASE_TERMINAL,
    RUN_STATES,
    RUN_TERMINAL,
    RUN_TO_TASK_SYNC,
    TASK_STATES,
    TASK_TERMINAL,
    VERSION_STATES,
    VERSION_TERMINAL,
)
from app.core.state_machines.engine import InvalidTransition, StateMachine

# Pre-built state machine instances
AGENT_SM = StateMachine("Agent", AGENT_STATES, AGENT_TERMINAL)
VERSION_SM = StateMachine("AgentVersion", VERSION_STATES, VERSION_TERMINAL)
RELEASE_SM = StateMachine("AgentRelease", RELEASE_STATES, RELEASE_TERMINAL)
RUN_SM = StateMachine("AgentRun", RUN_STATES, RUN_TERMINAL)
EXECUTION_SM = StateMachine("Execution", EXECUTION_STATES, EXECUTION_TERMINAL)
TASK_SM = StateMachine("Task", TASK_STATES, TASK_TERMINAL)

__all__ = [
    "AGENT_SM",
    "VERSION_SM",
    "RELEASE_SM",
    "RUN_SM",
    "EXECUTION_SM",
    "TASK_SM",
    "InvalidTransition",
    "StateMachine",
    "RUN_TO_TASK_SYNC",
    "AGENT_STATES",
    "VERSION_STATES",
    "RELEASE_STATES",
    "RUN_STATES",
    "EXECUTION_STATES",
    "TASK_STATES",
]
