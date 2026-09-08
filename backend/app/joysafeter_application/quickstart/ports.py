"""Ports for deterministic quickstart recommendation orchestration."""

from __future__ import annotations

from typing import Protocol

from app.joysafeter_domain.quickstart import ConnectionInput
from app.joysafeter_shared.ids import ProjectId


class QuickstartModelConnectionReaderPort(Protocol):
    async def list_for_project(self, project_id: ProjectId) -> list[ConnectionInput]:
        """Return active/inactive model connections projected for engine ranking."""
        ...
