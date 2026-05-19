"""Skill port — type-safe interface for skill loading in core/."""

from __future__ import annotations

from typing import Any, List, Protocol, runtime_checkable


@runtime_checkable
class SkillPort(Protocol):
    """Port for skill listing and retrieval.

    Implemented by: services/skill_service.py (SkillService)
    Used by: core/graph/deep_agents/skills_loader.py, core/skill/sandbox_loader.py
    """

    async def list_skills(self, current_user_id: str, include_public: bool = False) -> List[Any]: ...

    async def get_skill(self, skill_id: Any, **kwargs: Any) -> Any: ...
