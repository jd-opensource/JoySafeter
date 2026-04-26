"""Tests for AgentPublishService and retire status sync."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.agent_publish_service import AgentPublishService
from app.services.agent_release_service import AgentReleaseService


class TestInferRuntimeKind:
    def test_graph(self):
        assert AgentPublishService._infer_runtime_kind("graph") == "graph"

    def test_hybrid(self):
        assert AgentPublishService._infer_runtime_kind("hybrid") == "graph"

    def test_code(self):
        assert AgentPublishService._infer_runtime_kind("code") == "sandbox"

    def test_unknown_defaults_to_graph(self):
        assert AgentPublishService._infer_runtime_kind("whatever") == "graph"


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
