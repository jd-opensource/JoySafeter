"""Registry for long-running agent run definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class AgentDefinition:
    agent_name: str
    display_name: str
    run_type: str
    reducer: Callable[..., dict[str, Any]]
    make_initial_projection: Callable[[dict[str, Any], str], dict[str, Any]]


class AgentRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, AgentDefinition] = {}
        self._bootstrapped = False

    def _ensure_loaded(self) -> None:
        if self._bootstrapped:
            return
        self._bootstrapped = True
        from app.services import run_reducers  # noqa: F401

    def register(self, definition: AgentDefinition) -> AgentDefinition:
        self._definitions[definition.agent_name] = definition
        return definition

    def get(self, agent_name: str) -> AgentDefinition:
        self._ensure_loaded()
        definition = self.find(agent_name)
        if definition is None:
            raise KeyError(f"Unknown agent definition: {agent_name}")
        return definition

    def find(self, agent_name: str | None) -> AgentDefinition | None:
        self._ensure_loaded()
        if not agent_name:
            return None
        return self._definitions.get(agent_name)

    def list_definitions(self) -> list[AgentDefinition]:
        self._ensure_loaded()
        return sorted(self._definitions.values(), key=lambda definition: definition.display_name.lower())


agent_registry = AgentRegistry()
