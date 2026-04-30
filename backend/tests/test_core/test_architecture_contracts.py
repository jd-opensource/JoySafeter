from __future__ import annotations

from typing import get_args

from app.core.contracts.agent import (
    CLI_DEFINITION_KINDS,
    DEFINITION_KINDS,
    DEFINITION_RUNTIME_KIND,
    RUNTIME_KINDS,
    DefinitionKindLiteral,
    RuntimeKindLiteral,
    infer_runtime_kind,
    is_cli_definition_kind,
)
from app.core.contracts.execution import (
    EXECUTION_STATUSES,
    RELEASE_STATUSES,
    RUN_STATUSES,
    TRIGGER_SOURCES,
    ExecutionStatusLiteral,
    ReleaseStatusLiteral,
    RunStatusLiteral,
    TriggerSourceLiteral,
)
from app.core.engine import engine_registry
from app.core.engine.protocol import EngineCapabilities
from app.models.agent import AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution


def test_agent_contract_literals_match_runtime_sets() -> None:
    assert set(get_args(DefinitionKindLiteral)) == DEFINITION_KINDS
    assert set(get_args(RuntimeKindLiteral)) == RUNTIME_KINDS
    assert CLI_DEFINITION_KINDS == {"claude_code", "codex", "openclaw"}
    assert DEFINITION_RUNTIME_KIND == {
        "graph": "graph",
        "code": "code",
        "claude_code": "sandbox",
        "codex": "sandbox",
        "openclaw": "sandbox",
    }


def test_infer_runtime_kind_maps_every_definition_kind() -> None:
    assert {kind: infer_runtime_kind(kind) for kind in DEFINITION_KINDS} == DEFINITION_RUNTIME_KIND
    assert is_cli_definition_kind("claude_code") is True
    assert is_cli_definition_kind("graph") is False


def test_execution_contract_literals_match_runtime_sets() -> None:
    assert set(get_args(RunStatusLiteral)) == RUN_STATUSES
    assert set(get_args(ExecutionStatusLiteral)) == EXECUTION_STATUSES
    assert set(get_args(ReleaseStatusLiteral)) == RELEASE_STATUSES
    assert set(get_args(TriggerSourceLiteral)) == TRIGGER_SOURCES
    assert {"draft_test", "draft_copilot", "debug", "copilot"}.issubset(TRIGGER_SOURCES)


def _enum_values(model, column_name: str) -> set[str]:
    column = model.__table__.columns[column_name]
    return set(column.type.enums)


def test_model_status_enums_match_contracts() -> None:
    assert _enum_values(AgentRun, "status") == RUN_STATUSES
    assert _enum_values(Execution, "status") == EXECUTION_STATUSES
    assert _enum_values(AgentRelease, "status") == RELEASE_STATUSES


def test_registered_engines_declare_capabilities() -> None:
    for runtime_kind in ["sandbox", "graph", "code", "copilot"]:
        engine = engine_registry.get(runtime_kind)
        assert isinstance(engine.capabilities, EngineCapabilities)


def test_registered_engines_declare_message_injection_capabilities() -> None:
    assert {
        runtime_kind: engine_registry.get(runtime_kind).capabilities.supports_message_injection
        for runtime_kind in ["sandbox", "graph", "code", "copilot"]
    } == {
        "sandbox": True,
        "graph": False,
        "code": False,
        "copilot": False,
    }
