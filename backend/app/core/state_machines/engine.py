"""Generic state machine engine."""

from __future__ import annotations


class InvalidTransition(Exception):
    """Raised when a status transition violates the state machine rules."""

    def __init__(self, entity: str, from_status: str, to_status: str):
        self.entity = entity
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"{entity}: cannot transition from '{from_status}' to '{to_status}'"
        )


class StateMachine:
    """
    Validates status transitions against a declared transition table.

    Usage:
        sm = StateMachine("AgentRun", RUN_STATES, RUN_TERMINAL)
        sm.validate("pending", "running")   # OK
        sm.validate("succeeded", "running") # raises InvalidTransition
    """

    def __init__(
        self,
        name: str,
        transitions: dict[str, set[str]],
        terminal: set[str],
    ):
        self.name = name
        self._transitions = transitions
        self._terminal = terminal

    def validate(self, from_status: str, to_status: str) -> None:
        allowed = self._transitions.get(from_status)
        if allowed is None:
            raise InvalidTransition(self.name, from_status, to_status)
        if to_status not in allowed:
            raise InvalidTransition(self.name, from_status, to_status)

    def is_terminal(self, status: str) -> bool:
        return status in self._terminal

    @property
    def all_statuses(self) -> set[str]:
        return set(self._transitions.keys())

    @property
    def initial_statuses(self) -> set[str]:
        """Statuses that are not a target of any transition (entry points)."""
        all_targets: set[str] = set()
        for targets in self._transitions.values():
            all_targets |= targets
        return self.all_statuses - all_targets
