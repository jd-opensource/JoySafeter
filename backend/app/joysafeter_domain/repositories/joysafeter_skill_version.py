"""Skill Version Repository."""

from __future__ import annotations

from typing import Any, List, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkillVersion, JoySafeterSkillVersionFile
from app.joysafeter_domain.pagination import apply_ordered_cursor
from app.joysafeter_shared.ids import SkillId, SkillVersionId

from .base import BaseRepository


class SkillVersionRepository(BaseRepository[JoySafeterSkillVersion]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkillVersion, db)

    async def list_by_skill(
        self,
        skill_id: SkillId,
        *,
        limit: Optional[int] = None,
        after_id: Optional[SkillVersionId] = None,
    ) -> List[JoySafeterSkillVersion]:
        """List a skill's versions, newest first.

        Cursor pagination: the route declares ``limit`` / ``after_id`` — honor
        them here instead of returning everything and hardcoding
        ``has_more=False``. Ordering is
        ``(published_at DESC, id DESC)`` so the tiebreak is stable when several
        versions share a ``published_at`` (or it is NULL). ``after_id`` names
        the last row the caller already saw; we resume strictly after it via the
        shared keyset helper. When ``limit`` is given we over-fetch one row to
        tell the service whether more remain (the service trims + reports
        has_more).
        """
        stmt = (
            select(JoySafeterSkillVersion)
            .where(JoySafeterSkillVersion.skill_id == skill_id)
            .options(selectinload(JoySafeterSkillVersion.files))
        )
        stmt = apply_ordered_cursor(
            stmt,
            JoySafeterSkillVersion,
            after_id,
            JoySafeterSkillVersion.published_at,
            descending=True,
        )
        if limit is not None:
            # Over-fetch one so the service can compute has_more without a
            # second COUNT query.
            stmt = stmt.limit(limit + 1)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())  # type: ignore[return-value]

    async def get_latest(self, skill_id: SkillId) -> Optional[JoySafeterSkillVersion]:
        result = await self.db.execute(
            select(JoySafeterSkillVersion)
            .where(JoySafeterSkillVersion.skill_id == skill_id)
            .options(selectinload(JoySafeterSkillVersion.files))
            .order_by(JoySafeterSkillVersion.published_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def latest_version_map(self, skill_ids: List[SkillId]) -> dict[SkillId, str]:
        """Return ``{skill_id: latest_version_string}`` for the given skills.

        Only skills that have at least one published version appear in the
        map — a skill with no versions is simply absent. Runs in a single
        query (no per-skill round trips) so the skill *list* endpoint can
        cheaply annotate every row with its latest published version.
        """
        if not skill_ids:
            return {}
        result = await self.db.execute(
            select(
                JoySafeterSkillVersion.skill_id,
                JoySafeterSkillVersion.version,
                JoySafeterSkillVersion.published_at,
            ).where(JoySafeterSkillVersion.skill_id.in_(skill_ids))
        )
        latest: dict[SkillId, tuple[Any, str]] = {}
        for skill_id, version, published_at in result.all():
            current = latest.get(skill_id)
            if current is None or published_at > current[0]:
                latest[skill_id] = (published_at, version)
        return {skill_id: version for skill_id, (_, version) in latest.items()}

    async def get_by_version(self, skill_id: SkillId, version: str) -> Optional[JoySafeterSkillVersion]:
        result = await self.db.execute(
            select(JoySafeterSkillVersion)
            .where(
                and_(
                    JoySafeterSkillVersion.skill_id == skill_id,
                    JoySafeterSkillVersion.version == version,
                )
            )
            .options(selectinload(JoySafeterSkillVersion.files))
        )
        return result.scalar_one_or_none()  # type: ignore[return-value]

    async def get_highest_version_str(self, skill_id: SkillId) -> Optional[str]:
        """Return the highest semver version string for a skill.

        Raises ``InvalidRequestError`` (400) if any stored version string is
        not valid semver, rather than letting ``semver.Version.parse`` blow up
        with an unhandled ``ValueError`` (500). This is the single choke point
        for the auto-bump and the "> highest" precondition, so guarding it here
        covers every caller (the version route's auto-bump + ``publish_version``).
        """
        import semver

        from app.joysafeter_shared.common.app_errors import InvalidRequestError

        result = await self.db.execute(
            select(JoySafeterSkillVersion.version).where(JoySafeterSkillVersion.skill_id == skill_id)
        )
        version_strs = list(result.scalars().all())
        if not version_strs:
            return None
        try:
            version_strs.sort(key=lambda v: semver.Version.parse(v), reverse=True)
        except ValueError as exc:
            raise InvalidRequestError(
                "A stored skill version is not valid semver; cannot compute the next version.",
                code="SKILL_VERSION_STORED_INVALID",
                data={"skill_id": str(skill_id), "versions": version_strs},
            ) from exc
        return version_strs[0]


class SkillVersionFileRepository(BaseRepository[JoySafeterSkillVersionFile]):
    def __init__(self, db: AsyncSession):
        super().__init__(JoySafeterSkillVersionFile, db)

    async def list_by_version(self, version_id: SkillVersionId) -> List[JoySafeterSkillVersionFile]:
        result = await self.db.execute(
            select(JoySafeterSkillVersionFile).where(JoySafeterSkillVersionFile.version_id == version_id)
        )
        return list(result.scalars().all())
