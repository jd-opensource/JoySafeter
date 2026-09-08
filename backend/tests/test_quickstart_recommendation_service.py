import pytest

from app.joysafeter_application.quickstart.recommendation_service import (
    QuickstartRecommendationService,
)
from app.joysafeter_domain.quickstart import ConnectionInput, EngineInput, QuickstartPhase
from app.joysafeter_shared.ids import ProjectId

pytestmark = pytest.mark.no_db


def _engines():
    return [
        EngineInput("native", "Native", True),
        EngineInput("claude", "Claude Code", True),
        EngineInput("codex", "Codex", True),
    ]


class _ConnectionReader:
    async def list_for_project(self, project_id):
        assert type(project_id) is ProjectId
        return [ConnectionInput(("codex",), True, False)]


async def test_unified_recommend_entry_point_owns_understand_orchestration():
    svc = QuickstartRecommendationService(
        engines=tuple(_engines()),
        connection_reader=_ConnectionReader(),
    )
    rec = await svc.recommend(
        phase=QuickstartPhase.UNDERSTAND,
        project_id=ProjectId.new(),
        intent_text="build a coding agent",
        agent_config=None,
    )
    assert rec.engine is not None
    assert rec.engine.recommended_engine_id == "codex"


def test_recommend_engine_returns_ranked_options():
    svc = QuickstartRecommendationService()
    rec = svc.recommend_engine(
        intent_text="fix a bug in my python repo",
        enabled_engines=_engines(),
        connections=[ConnectionInput(("claude",), True, False)],
    )
    assert rec.phase == "understand"
    assert rec.engine.recommended_engine_id == "claude"
    assert {o.engine_id for o in rec.engine.options} == {"native", "claude", "codex"}


def test_recommend_engine_can_recommend_setup_when_nothing_is_ready():
    svc = QuickstartRecommendationService()
    rec = svc.recommend_engine(intent_text="write a poem", enabled_engines=_engines(), connections=[])
    assert rec.engine.recommended_engine_id == "native"
    assert rec.engine.options[0].readiness == "setup_required"


async def test_secure_returns_deterministic_host_recommendations():
    svc = QuickstartRecommendationService()
    rec = await svc.recommend_security(intent_text="summarize my github pull requests", agent_config=None)
    assert rec.phase == "secure"
    assert set(rec.environment.allowed_hosts) >= {"github.com", "api.github.com"}


async def test_secure_returns_empty_optional_recommendations_without_signal():
    svc = QuickstartRecommendationService()
    rec = await svc.recommend_security(intent_text="do something generic", agent_config=None)
    assert rec.environment.allowed_hosts == []
    assert rec.credential_group is None


async def test_secure_projects_every_remote_mcp_server_with_auth_requirement():
    svc = QuickstartRecommendationService()
    rec = await svc.recommend_security(
        intent_text="old request mentioned GitHub",
        agent_config={
            "mcp_servers": [
                {
                    "type": "streamable_http",
                    "name": "GitHub",
                    "url": "https://mcp.github.example/v1",
                    "auth_requirement": "required",
                },
                {
                    "type": "sse",
                    "name": "Public Search",
                    "url": "https://search.example.org/sse",
                    "auth_requirement": "none",
                },
                {
                    "type": "local_stdio",
                    "name": "Local helper",
                    "command": "helper",
                },
            ]
        },
    )

    assert rec.credential_group is not None
    assert [server.model_dump() for server in rec.credential_group.mcp_servers] == [
        {
            "name": "GitHub",
            "url": "https://mcp.github.example/v1",
            "auth_requirement": "required",
        },
    ]


async def test_secure_does_not_recommend_credential_group_for_local_or_no_auth_mcp():
    svc = QuickstartRecommendationService()
    rec = await svc.recommend_security(
        intent_text="",
        agent_config={
            "mcp_servers": [
                {"type": "local_stdio", "name": "local", "command": "node"},
                {
                    "type": "sse",
                    "name": "events",
                    "url": "https://events.example.com/sse",
                    "auth_requirement": "none",
                },
            ]
        },
    )

    assert rec.credential_group is None
