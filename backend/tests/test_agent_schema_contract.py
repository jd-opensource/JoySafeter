import pytest
from pydantic import ValidationError

from app.joysafeter_api.api.v1.quickstart import QuickstartAgentContext
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
)
from app.joysafeter_shared.ids import SkillId

pytestmark = pytest.mark.no_db


def test_agent_requests_use_system_field() -> None:
    create = JoySafeterCreateAgentRequest(name="Agent", engine_kind="claude", system="Be precise")
    update = JoySafeterUpdateAgentRequest(system="Be concise")

    assert create.system == "Be precise"
    assert update.system == "Be concise"


def test_agent_create_requires_explicit_engine_kind() -> None:
    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(name="Agent")


@pytest.mark.parametrize("request_type", [JoySafeterCreateAgentRequest, JoySafeterUpdateAgentRequest])
def test_agent_requests_reject_removed_system_prompt_field(request_type) -> None:
    payload = {"system_prompt": "old field"}
    if request_type is JoySafeterCreateAgentRequest:
        payload["name"] = "Agent"
        payload["engine_kind"] = "claude"

    with pytest.raises(ValidationError):
        request_type(**payload)


def test_agent_skill_refs_reject_packed_archives_and_drafts() -> None:
    skill_id = SkillId.new()

    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(
            name="Agent",
            engine_kind="claude",
            skills=[{"name": "packed", "tar_gz_b64": "eA=="}],
        )

    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(
            name="Agent",
            engine_kind="claude",
            skills=[{"type": "custom", "skill_id": str(skill_id), "version": "draft"}],
        )


def test_agent_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        JoySafeterCreateAgentRequest(name="Agent", engine_kind="claude", skill_ids=["skill_123"])


def test_quickstart_context_uses_system_field() -> None:
    context = QuickstartAgentContext(name="Agent", system="Be precise")
    assert context.system == "Be precise"
    assert "secret_ref" not in QuickstartAgentContext.model_fields

    with pytest.raises(ValidationError):
        QuickstartAgentContext(name="Agent", system_prompt="old field")
