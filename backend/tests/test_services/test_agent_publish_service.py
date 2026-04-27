"""Tests for AgentPublishService and retire status sync."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.common.app_errors import InvalidRequestError, NotFoundError
from app.services.agent_publish_service import AgentPublishService
from app.services.agent_release_service import AgentReleaseService


class TestInferRuntimeKind:
    def test_graph(self):
        assert AgentPublishService._infer_runtime_kind("graph") == "graph"

    def test_code(self):
        assert AgentPublishService._infer_runtime_kind("code") == "code"

    @pytest.mark.parametrize("definition_kind", ["claude_code", "codex", "openclaw"])
    def test_cli_provider_definitions_run_in_sandbox(self, definition_kind: str):
        assert AgentPublishService._infer_runtime_kind(definition_kind) == "sandbox"

    @pytest.mark.parametrize("definition_kind", ["prompt", "hybrid", "cli", "copilot", "whatever"])
    def test_unsupported_definition_kind_is_rejected(self, definition_kind: str):
        with pytest.raises(InvalidRequestError):
            AgentPublishService._infer_runtime_kind(definition_kind)


class TestPublishRuntimeBinding:
    def _make_service(self) -> AgentPublishService:
        db = AsyncMock()
        svc = AgentPublishService.__new__(AgentPublishService)
        svc.db = db
        svc.version_svc = AsyncMock()
        svc.release_svc = AsyncMock()
        svc.agent_repo = AsyncMock()
        svc.version_repo = AsyncMock()
        svc.safe_commit = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_cli_provider_definition_sets_sandbox_runtime_type(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        version_id = uuid.uuid4()
        release_id = uuid.uuid4()
        user_id = "user-1"

        agent = SimpleNamespace(id=agent_id, current_draft_version_id=version_id)
        version = SimpleNamespace(id=version_id, status="draft", definition_kind="codex")
        release = SimpleNamespace(id=release_id)

        svc.agent_repo.get = AsyncMock(return_value=agent)
        svc.version_repo.get = AsyncMock(return_value=version)
        svc.release_svc.publish_release = AsyncMock(return_value=release)
        svc.release_svc.activate_release = AsyncMock()

        await svc.publish(agent_id, user_id)

        request = svc.release_svc.publish_release.await_args.args[2]
        assert request.runtime_kind == "sandbox"
        assert request.runtime_binding == {"runtime_type": "codex"}

    @pytest.mark.asyncio
    async def test_graph_definition_keeps_empty_runtime_binding(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        version_id = uuid.uuid4()
        release_id = uuid.uuid4()
        user_id = "user-1"

        agent = SimpleNamespace(id=agent_id, current_draft_version_id=version_id)
        version = SimpleNamespace(id=version_id, status="draft", definition_kind="graph")
        release = SimpleNamespace(id=release_id)

        svc.agent_repo.get = AsyncMock(return_value=agent)
        svc.version_repo.get = AsyncMock(return_value=version)
        svc.release_svc.publish_release = AsyncMock(return_value=release)
        svc.release_svc.activate_release = AsyncMock()

        await svc.publish(agent_id, user_id)

        request = svc.release_svc.publish_release.await_args.args[2]
        assert request.runtime_kind == "graph"
        assert request.runtime_binding == {}

    @pytest.mark.asyncio
    async def test_publish_missing_agent_has_canonical_code(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()

        svc.agent_repo.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError) as exc_info:
            await svc.publish(agent_id, "user-1")

        assert exc_info.value.code == "AGENT_NOT_FOUND"
        assert exc_info.value.data == {"agent_id": str(agent_id)}

    @pytest.mark.asyncio
    async def test_publish_missing_draft_version_has_canonical_code(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        agent = SimpleNamespace(id=agent_id, current_draft_version_id=None)

        svc.agent_repo.get = AsyncMock(return_value=agent)

        with pytest.raises(InvalidRequestError) as exc_info:
            await svc.publish(agent_id, "user-1")

        assert exc_info.value.code == "AGENT_DRAFT_VERSION_MISSING"


class TestRetireStatusSync:
    """Retiring the active release should sync agent.status back to draft."""

    def _make_service(self) -> AgentReleaseService:
        db = AsyncMock()
        svc = AgentReleaseService.__new__(AgentReleaseService)
        svc.db = db
        svc.release_repo = AsyncMock()
        svc.version_repo = AsyncMock()
        svc.agent_repo = AsyncMock()
        return svc

    def _make_release(self, release_id: uuid.UUID, status: str = "ready"):
        return SimpleNamespace(
            id=release_id, status=status, agent_version_id=uuid.uuid4(),
            release_number=1, runtime_kind="graph", published_at=None, retired_at=None,
        )

    def _make_agent(
        self, agent_id: uuid.UUID, active_release_id: uuid.UUID | None, status: str = "active",
    ):
        return SimpleNamespace(
            id=agent_id, status=status, active_release_id=active_release_id,
        )

    @pytest.mark.asyncio
    async def test_retire_active_release_reverts_status_to_draft(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        release_id = uuid.uuid4()

        release = self._make_release(release_id)
        agent = self._make_agent(agent_id, active_release_id=release_id, status="active")

        svc.release_repo.get = AsyncMock(return_value=release)
        svc.release_repo.update = AsyncMock(return_value=release)
        svc.agent_repo.get = AsyncMock(return_value=agent)
        svc.agent_repo.update = AsyncMock()

        await svc.retire_release(agent_id, release_id)

        svc.agent_repo.update.assert_called_once_with(
            agent_id, {"active_release_id": None, "status": "draft"},
        )

    @pytest.mark.asyncio
    async def test_retire_active_release_preserves_archived_status(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        release_id = uuid.uuid4()

        release = self._make_release(release_id)
        agent = self._make_agent(agent_id, active_release_id=release_id, status="archived")

        svc.release_repo.get = AsyncMock(return_value=release)
        svc.release_repo.update = AsyncMock(return_value=release)
        svc.agent_repo.get = AsyncMock(return_value=agent)
        svc.agent_repo.update = AsyncMock()

        await svc.retire_release(agent_id, release_id)

        svc.agent_repo.update.assert_called_once_with(
            agent_id, {"active_release_id": None},
        )

    @pytest.mark.asyncio
    async def test_retire_non_active_release_leaves_agent_unchanged(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        active_release_id = uuid.uuid4()
        other_release_id = uuid.uuid4()

        release = self._make_release(other_release_id)
        agent = self._make_agent(agent_id, active_release_id=active_release_id, status="active")

        svc.release_repo.get = AsyncMock(return_value=release)
        svc.release_repo.update = AsyncMock(return_value=release)
        svc.agent_repo.get = AsyncMock(return_value=agent)
        svc.agent_repo.update = AsyncMock()

        await svc.retire_release(agent_id, other_release_id)

        svc.agent_repo.update.assert_not_called()


class TestAgentReleaseServiceErrors:
    def _make_service(self) -> AgentReleaseService:
        db = AsyncMock()
        svc = AgentReleaseService.__new__(AgentReleaseService)
        svc.db = db
        svc.release_repo = AsyncMock()
        svc.version_repo = AsyncMock()
        svc.agent_repo = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_publish_release_rejects_unfrozen_version_with_canonical_code(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        version_id = uuid.uuid4()
        svc.version_repo.get = AsyncMock(return_value=SimpleNamespace(id=version_id, agent_id=agent_id, status="draft"))

        with pytest.raises(InvalidRequestError) as exc_info:
            await svc.publish_release(
                agent_id,
                "user-1",
                SimpleNamespace(agent_version_id=version_id, runtime_kind="graph", builder_kind=None, runtime_binding={}),
            )

        assert exc_info.value.code == "AGENT_VERSION_NOT_FROZEN"

    @pytest.mark.asyncio
    async def test_activate_release_missing_agent_has_canonical_code(self):
        svc = self._make_service()
        agent_id = uuid.uuid4()
        release_id = uuid.uuid4()
        svc.release_repo.get = AsyncMock(return_value=SimpleNamespace(id=release_id, status="ready"))
        svc.agent_repo.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundError) as exc_info:
            await svc.activate_release(agent_id, release_id)

        assert exc_info.value.code == "AGENT_NOT_FOUND"
        assert exc_info.value.data == {"agent_id": str(agent_id)}
