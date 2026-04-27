"""Contracts for Agent definition/runtime kind enums."""

from __future__ import annotations

import pytest
import uuid
from pydantic import ValidationError

from app.schemas.agent import CreateAgentRequest
from app.schemas.agent_release import CreateAgentReleaseRequest
from app.schemas.agent_version import CreateAgentVersionRequest


@pytest.mark.parametrize("definition_kind", ["graph", "code", "claude_code", "codex", "openclaw"])
def test_create_agent_accepts_supported_definition_kinds(definition_kind: str) -> None:
    request = CreateAgentRequest(name="Agent", definition_kind=definition_kind)
    assert request.definition_kind == definition_kind


@pytest.mark.parametrize("definition_kind", ["prompt", "hybrid", "cli", "copilot"])
def test_create_agent_rejects_removed_definition_kinds(definition_kind: str) -> None:
    with pytest.raises(ValidationError):
        CreateAgentRequest(name="Agent", definition_kind=definition_kind)


@pytest.mark.parametrize("definition_kind", ["graph", "code", "claude_code", "codex", "openclaw"])
def test_create_version_accepts_supported_definition_kinds(definition_kind: str) -> None:
    request = CreateAgentVersionRequest(definition_kind=definition_kind)
    assert request.definition_kind == definition_kind


@pytest.mark.parametrize("definition_kind", ["prompt", "hybrid", "cli", "copilot"])
def test_create_version_rejects_removed_definition_kinds(definition_kind: str) -> None:
    with pytest.raises(ValidationError):
        CreateAgentVersionRequest(definition_kind=definition_kind)


@pytest.mark.parametrize("runtime_kind", ["graph", "code", "sandbox"])
def test_create_release_accepts_supported_runtime_kinds(runtime_kind: str) -> None:
    request = CreateAgentReleaseRequest(agent_version_id=uuid.uuid4(), runtime_kind=runtime_kind)
    assert request.runtime_kind == runtime_kind


@pytest.mark.parametrize("runtime_kind", ["copilot", "hosted", "external"])
def test_create_release_rejects_removed_runtime_kinds(runtime_kind: str) -> None:
    with pytest.raises(ValidationError):
        CreateAgentReleaseRequest(agent_version_id=uuid.uuid4(), runtime_kind=runtime_kind)
