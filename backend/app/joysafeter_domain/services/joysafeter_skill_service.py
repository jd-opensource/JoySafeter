"""
JoySafeter skill management services.

Merged from skill_service.py, skill_version_service.py, and
skill_lifecycle_service.py (v1 cleanup consolidation):
  - SkillService — skill CRUD + file management + scan dispatch
  - SkillVersionService — version publish / list / restore
  - SkillLifecycleService / LifecycleTransition — lifecycle state machine

Security/packing/runtime-policy live in joysafeter_skill_security.py.
"""

from __future__ import annotations

# ruff: noqa: E402 — sections merged verbatim; imports intentionally follow their banners

# ============================================================================
# skill_lifecycle_service.py
# ============================================================================

"""Skill lifecycle state machine.

A separate service so the transition rules are in one file and the API
endpoints in :mod:`app.joysafeter_api.api.v1.skills` stay thin. Every
transition writes back to ``Skill.lifecycle_status`` and commits.

Allowed edges
-------------

::

    draft           -> pending_review        (owner submits for review)
    pending_review  -> approved              (reviewer accepts)
    pending_review  -> rejected              (reviewer denies)
    rejected        -> draft                 (owner reopens to fix and resubmit)
    approved        -> archived              (owner retires the skill)
    archived        -> approved              (owner un-archives)

Every other edge raises ``InvalidRequestError`` with code
``SKILL_LIFECYCLE_INVALID_TRANSITION``.

Authorization
-------------

P1 lets the **owner** drive every transition (self-review). Once we have
admin reviewers the API layer can pass ``is_admin=True`` and the rules
unlock for cross-user approve/reject; until then, only the skill's owner
(or a collaborator with admin role) can call any transition.

Runtime gate interaction
------------------------

Transitions write only to ``lifecycle_status``; they don't trigger a
re-scan. The drift gate in
``skill_runtime_policy.is_skill_usable`` separately compares the current
content hash to the last scan's ``target_hash``, so a skill that drifts
between approve and load is still caught.
"""


import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterCollaboratorRole,
    JoySafeterSkillLifecycleStatus,
)
from app.joysafeter_domain.repositories.joysafeter_skill import SkillRepository
from app.joysafeter_shared.common.app_errors import (
    InvalidRequestError,
    NotFoundError,
)
from app.joysafeter_shared.common.skill_permissions import check_skill_access

# Edges that ``transition()`` accepts. Anything not in this set is a
# rejected transition; the empty target set on a state means "this is a
# terminal-from-here state for that direction".
_ALLOWED_EDGES: dict[str, frozenset[str]] = {
    JoySafeterSkillLifecycleStatus.DRAFT.value: frozenset({JoySafeterSkillLifecycleStatus.PENDING_REVIEW.value}),
    JoySafeterSkillLifecycleStatus.PENDING_REVIEW.value: frozenset(
        {JoySafeterSkillLifecycleStatus.APPROVED.value, JoySafeterSkillLifecycleStatus.REJECTED.value}
    ),
    JoySafeterSkillLifecycleStatus.REJECTED.value: frozenset({JoySafeterSkillLifecycleStatus.DRAFT.value}),
    JoySafeterSkillLifecycleStatus.APPROVED.value: frozenset({JoySafeterSkillLifecycleStatus.ARCHIVED.value}),
    JoySafeterSkillLifecycleStatus.ARCHIVED.value: frozenset({JoySafeterSkillLifecycleStatus.APPROVED.value}),
}


@dataclass(frozen=True)
class LifecycleTransition:
    """Result of a successful transition."""

    skill_id: uuid.UUID
    from_status: str
    to_status: str


class SkillLifecycleService:
    """State machine + persistence for ``Skill.lifecycle_status``."""

    def __init__(self, db: AsyncSession, *, active_org_id: Optional[str] = None):
        self.db = db
        self.skill_repo = SkillRepository(db)
        # P2.9: active org for strict isolation in ``check_skill_access``.
        # When the API layer constructs this service from a
        # JoySafeterAuthContext, the org id is threaded through so a
        # multi-org admin can't fire transitions from a different org
        # context. ``None`` falls back to pre-P2.9 behavior.
        self._active_org_id = active_org_id

    async def submit_for_review(self, skill_id: uuid.UUID, current_user_id: str) -> LifecycleTransition:
        """draft -> pending_review (owner action)."""
        return await self._transition(
            skill_id=skill_id,
            current_user_id=current_user_id,
            to_status=JoySafeterSkillLifecycleStatus.PENDING_REVIEW.value,
        )

    async def approve(self, skill_id: uuid.UUID, current_user_id: str) -> LifecycleTransition:
        """pending_review -> approved (self-review in P1, admin review in P2)."""
        return await self._transition(
            skill_id=skill_id,
            current_user_id=current_user_id,
            to_status=JoySafeterSkillLifecycleStatus.APPROVED.value,
        )

    async def reject(self, skill_id: uuid.UUID, current_user_id: str) -> LifecycleTransition:
        """pending_review -> rejected (reviewer denies)."""
        return await self._transition(
            skill_id=skill_id,
            current_user_id=current_user_id,
            to_status=JoySafeterSkillLifecycleStatus.REJECTED.value,
        )

    async def archive(self, skill_id: uuid.UUID, current_user_id: str) -> LifecycleTransition:
        """approved -> archived (owner retires)."""
        return await self._transition(
            skill_id=skill_id,
            current_user_id=current_user_id,
            to_status=JoySafeterSkillLifecycleStatus.ARCHIVED.value,
        )

    async def unarchive(self, skill_id: uuid.UUID, current_user_id: str) -> LifecycleTransition:
        """archived -> approved (owner brings it back online)."""
        return await self._transition(
            skill_id=skill_id,
            current_user_id=current_user_id,
            to_status=JoySafeterSkillLifecycleStatus.APPROVED.value,
        )

    async def reopen(self, skill_id: uuid.UUID, current_user_id: str) -> LifecycleTransition:
        """rejected -> draft (owner fixes issues and reopens)."""
        return await self._transition(
            skill_id=skill_id,
            current_user_id=current_user_id,
            to_status=JoySafeterSkillLifecycleStatus.DRAFT.value,
        )

    async def _transition(
        self,
        *,
        skill_id: uuid.UUID,
        current_user_id: str,
        to_status: str,
    ) -> LifecycleTransition:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError(
                "Skill not found",
                code="SKILL_NOT_FOUND",
                data={"skill_id": str(skill_id)},
            )

            # P1 authorization: only the owner (or a skill admin) can drive
            # the state machine. ``check_skill_access`` already understands
            # ownership + admin role on the collaborator table; reusing it
            # keeps the auth model consistent with the rest of skill writes.
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.ADMIN,
            active_org_id=self._active_org_id,
        )

        from_status = skill.lifecycle_status
        allowed = _ALLOWED_EDGES.get(from_status, frozenset())
        if to_status not in allowed:
            raise InvalidRequestError(
                f"Cannot transition skill from {from_status!r} to {to_status!r}",
                code="SKILL_LIFECYCLE_INVALID_TRANSITION",
                data={
                    "skill_id": str(skill_id),
                    "from_status": from_status,
                    "to_status": to_status,
                    "allowed": sorted(allowed),
                },
            )

        skill.lifecycle_status = to_status
        await self.db.commit()
        await self.db.refresh(skill)
        return LifecycleTransition(
            skill_id=skill_id,
            from_status=from_status,
            to_status=to_status,
        )


# ============================================================================
# skill_version_service.py
# ============================================================================

"""Skill Version Service — publish, list, get, delete, restore."""


from datetime import datetime, timezone
from typing import List

import semver

from app.joysafeter_domain.models.joysafeter_skill import (
    JoySafeterSkill,
    JoySafeterSkillFile,
    JoySafeterSkillVersion,
    JoySafeterSkillVersionFile,
)
from app.joysafeter_domain.repositories.joysafeter_skill import SkillFileRepository
from app.joysafeter_domain.repositories.joysafeter_skill_version import (
    SkillVersionFileRepository,
    SkillVersionRepository,
)
from app.joysafeter_shared.common.app_errors import ResourceConflictError

from .base import BaseService


class SkillVersionService(BaseService[JoySafeterSkillVersion]):
    def __init__(self, db, *, active_org_id: Optional[str] = None):
        super().__init__(db)
        self.repo = SkillVersionRepository(db)
        self.file_repo = SkillVersionFileRepository(db)
        self.skill_repo = SkillRepository(db)
        self.skill_file_repo = SkillFileRepository(db)
        # P2.10 — strict org isolation. Mirrors ``SkillService`` and
        # ``SkillSecurityService``: threaded through to every
        # ``check_skill_access`` call below so version reads / writes
        # also respect the caller's active org context. ``None``
        # falls back to pre-P2.9 cross-org-friendly behavior; legacy
        # callers stay safe.
        self._active_org_id = active_org_id

    async def publish_version(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        version_str: str,
        release_notes: Optional[str] = None,
        is_superuser: bool = False,
    ) -> JoySafeterSkillVersion:
        skill = await self._get_skill_with_files_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.ADMIN,
            is_superuser=is_superuser,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Security gate — refuse to publish a high-risk skill. ``blocked`` is
        # the verdict SkillSpector assigns when a scan finds HIGH/CRITICAL
        # issues; the runtime already refuses to load such skills
        # (``is_skill_usable``), so publishing a snapshot that no agent could
        # ever run is meaningless and dangerous. Only ``blocked`` is gated
        # here — ``warning``/``passed`` publish normally, and un-scanned /
        # in-flight states are intentionally not blocked.
        if skill.security_status == "blocked":
            raise InvalidRequestError(
                "技能存在高安全风险，已被安全扫描拦截，无法发布版本。请修复后重新扫描。",
                code="SKILL_SECURITY_BLOCKED",
                data={
                    "security_status": skill.security_status,
                    "security_severity": skill.security_severity,
                    "security_score": skill.security_score,
                },
            )

        # Validate semver format
        try:
            new_ver = semver.Version.parse(version_str)
        except ValueError:
            raise InvalidRequestError(
                f"Invalid version format: '{version_str}'. Must be MAJOR.MINOR.PATCH",
                code="SKILL_VERSION_FORMAT_INVALID",
                data={"version": version_str},
            )
            # Reject pre-release / build metadata
        if new_ver.prerelease or new_ver.build:
            raise InvalidRequestError(
                "Pre-release and build metadata are not supported", code="SKILL_VERSION_PRERELEASE_UNSUPPORTED"
            )

            # Check > highest existing
        highest_str = await self.repo.get_highest_version_str(skill_id)
        if highest_str:
            highest = semver.Version.parse(highest_str)
            if new_ver <= highest:
                raise InvalidRequestError(
                    f"Version {version_str} must be greater than current highest {highest_str}",
                    code="SKILL_VERSION_NOT_GREATER_THAN_LATEST",
                    data={"version": version_str, "latest_version": highest_str},
                )

                # Snapshot
        sv = JoySafeterSkillVersion(
            skill_id=skill_id,
            version=version_str,
            release_notes=release_notes,
            skill_name=skill.name,
            skill_description=skill.description,
            content=skill.content,
            tags=list(skill.tags) if skill.tags else [],
            meta_data=dict(skill.meta_data) if skill.meta_data else {},
            allowed_tools=list(skill.allowed_tools) if skill.allowed_tools else [],
            compatibility=skill.compatibility,
            license=skill.license,
            published_by_id=current_user_id,
            published_at=datetime.now(timezone.utc),
        )
        self.db.add(sv)
        await self.db.flush()
        await self.db.refresh(sv)

        # Copy files
        skill_files = await self.skill_file_repo.list_by_skill(skill_id)
        for sf in skill_files:
            vf = JoySafeterSkillVersionFile(
                version_id=sv.id,
                path=sf.path,
                file_name=sf.file_name,
                file_type=sf.file_type,
                content=sf.content,
                storage_type=sf.storage_type,
                storage_key=sf.storage_key,
                size=sf.size,
            )
            self.db.add(vf)

        await self.db.commit()
        await self.db.refresh(sv)
        return sv

    async def list_versions(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> List[JoySafeterSkillVersion]:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.VIEWER,
            is_superuser=is_superuser,
            active_org_id=self._active_org_id,
        )
        return await self.repo.list_by_skill(skill_id)  # type: ignore[return-value,no-any-return]

    async def get_version(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> JoySafeterSkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.VIEWER,
            is_superuser=is_superuser,
            active_org_id=self._active_org_id,
        )
        sv = await self.repo.get_by_version(skill_id, version_str)
        if not sv:
            raise NotFoundError(
                "Skill version not found",
                code="SKILL_VERSION_NOT_FOUND",
                data={"skill_id": str(skill_id), "version": version_str},
            )
        return sv  # type: ignore[return-value,no-any-return]

    async def get_latest_version(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> JoySafeterSkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.VIEWER,
            is_superuser=is_superuser,
            active_org_id=self._active_org_id,
        )
        sv = await self.repo.get_latest(skill_id)
        if not sv:
            raise NotFoundError(
                "No published versions found", code="SKILL_VERSION_NOT_FOUND", data={"skill_id": str(skill_id)}
            )
        return sv  # type: ignore[return-value,no-any-return]

    async def delete_version(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
        force: bool = False,
    ) -> None:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.ADMIN,
            is_superuser=is_superuser,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)
        sv = await self.repo.get_by_version(skill_id, version_str)
        if not sv:
            raise NotFoundError(
                "Skill version not found",
                code="SKILL_VERSION_NOT_FOUND",
                data={"skill_id": str(skill_id), "version": version_str},
            )

            # Reference check: any live agent.skills OR persisted agent_version
            # snapshot.skills entry that points at this specific version.
        if not force:
            referrers = await self._find_version_referrers(skill_id, version_str)
            if referrers:
                raise ResourceConflictError(
                    "Skill version is in use",
                    code="SKILL_VERSION_IN_USE",
                    data={
                        "skill_id": str(skill_id),
                        "version": version_str,
                        "referrers": referrers,
                        "hint": "Pass force=true to delete anyway. Agents pointing at this version will fall back according to their current 'version' field.",
                    },
                )

        await self.db.delete(sv)
        await self.db.commit()

    async def _find_version_referrers(self, skill_id: uuid.UUID, version_str: str) -> list[dict]:
        """Find agents (live draft + persisted agent_versions) that reference
        ``(skill_id, version_str)`` in their ``skills`` array. Returns a list
        of compact descriptors usable in the error payload."""
        import json

        from sqlalchemy import text as sa_text

        # JSONB array containment: skills @> [{"skill_id": "...", "version": "..."}]
        sid_str = str(skill_id)
        # Match both prefixed and unprefixed skill_id forms — the codebase uses
        # both shapes in different paths.
        candidates = [
            json.dumps([{"skill_id": sid_str, "version": version_str}]),
            json.dumps([{"skill_id": f"skill_{sid_str}", "version": version_str}]),
        ]

        referrers: list[dict] = []

        # 1) Live agent.skills
        for needle in candidates:
            stmt = sa_text("SELECT id, name FROM joysafeter_agents WHERE skills @> CAST(:needle AS jsonb)").bindparams(
                needle=needle
            )
            result = await self.db.execute(stmt)
            for row in result.mappings():
                referrers.append(
                    {
                        "kind": "agent",
                        "agent_id": str(row["id"]),
                        "name": row["name"],
                    }
                )

                # 2) Frozen agent_version snapshots
        for needle in candidates:
            stmt = sa_text(
                "SELECT agent_id, version FROM joysafeter_agent_versions "
                "WHERE (snapshot->'skills') @> CAST(:needle AS jsonb)"
            ).bindparams(needle=needle)
            result = await self.db.execute(stmt)
            for row in result.mappings():
                referrers.append(
                    {
                        "kind": "agent_version",
                        "agent_id": str(row["agent_id"]),
                        "agent_version": row["version"],
                    }
                )

        return referrers

    async def restore_draft(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> JoySafeterSkill:
        skill = await self._get_skill_with_files_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.ADMIN,
            is_superuser=is_superuser,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)
        sv = await self.repo.get_by_version(skill_id, version_str)
        if not sv:
            raise NotFoundError(
                "Skill version not found",
                code="SKILL_VERSION_NOT_FOUND",
                data={"skill_id": str(skill_id), "version": version_str},
            )

            # Overwrite draft
        skill.name = sv.skill_name
        skill.description = sv.skill_description
        skill.content = sv.content
        skill.tags = list(sv.tags) if sv.tags else []
        skill.meta_data = dict(sv.meta_data) if sv.meta_data else {}
        skill.allowed_tools = list(sv.allowed_tools) if sv.allowed_tools else []
        skill.compatibility = sv.compatibility
        skill.license = sv.license

        # Replace draft files
        await self.skill_file_repo.delete_by_skill(skill_id)
        version_files = await self.file_repo.list_by_version(sv.id)
        for vf in version_files:
            sf = JoySafeterSkillFile(
                skill_id=skill_id,
                path=vf.path,
                file_name=vf.file_name,
                file_type=vf.file_type,
                content=vf.content,
                storage_type=vf.storage_type,
                storage_key=vf.storage_key,
                size=vf.size,
            )
            self.db.add(sf)

        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def _get_skill_or_404(self, skill_id: uuid.UUID) -> JoySafeterSkill:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        return skill  # type: ignore[return-value,no-any-return]

    async def _get_skill_with_files_or_404(self, skill_id: uuid.UUID) -> JoySafeterSkill:
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        return skill  # type: ignore[return-value,no-any-return]


# ============================================================================
# skill_service.py
# ============================================================================

"""
Skill Service: Permission Check + CRUD
"""


from pathlib import Path
from typing import Any, Dict, Literal, Union

from loguru import logger

from app.joysafeter_shared.common.app_errors import AccessDeniedError
from app.joysafeter_shared.skill.validators import (
    truncate_compatibility,
    truncate_description,
    validate_compatibility,
    validate_skill_description,
    validate_skill_name,
)
from app.joysafeter_shared.skill.yaml_parser import (
    extract_metadata_from_frontmatter,
    is_system_file,
    is_valid_text_content,
    parse_skill_md,
    validate_file_extension,
)

from .base import BaseService
from .joysafeter_skill_security import SkillSecurityService


def _skill_archived_error(skill) -> ResourceConflictError:
    return ResourceConflictError(
        "Skill is archived and read-only. Unarchive before editing.",
        code="SKILL_ARCHIVED",
        data={"skill_id": str(skill.id)},
        retryable=False,
        user_action="refresh",
    )


def _ensure_skill_mutable(skill) -> None:
    if getattr(skill, "lifecycle_status", None) == JoySafeterSkillLifecycleStatus.ARCHIVED.value:
        raise _skill_archived_error(skill)


class SkillService(BaseService[JoySafeterSkill]):
    def __init__(self, db, *, active_org_id: Optional[str] = None):
        super().__init__(db)
        self.repo = SkillRepository(db)
        self.file_repo = SkillFileRepository(db)
        self.security_service = SkillSecurityService(db, active_org_id=active_org_id)
        # P2.9: when the API layer constructs ``SkillService`` it
        # passes ``JoySafeterAuthContext.org_id`` here. The service
        # then threads it into every ``check_skill_access`` call so
        # owner / collaborator short-circuits respect strict org
        # isolation — owners can't read their own skill while pinned
        # to a different org context. ``None`` falls back to the
        # pre-P2.9 behavior (cross-org owner reads allowed); kept for
        # legacy callers we haven't migrated yet.
        self._active_org_id = active_org_id
        # P2: BG-task descriptors that the API layer should hand to
        # FastAPI's ``BackgroundTasks`` once the request DB session
        # commits. Each entry is a plain dict of the kwargs that
        # ``run_scan_in_background`` accepts. The service NEVER spawns
        # tasks itself — that would tie domain logic to FastAPI's
        # request scope. Call ``drain_pending_async_scans()`` at the
        # API boundary to consume.
        self._pending_async_scans: list[dict] = []

    def drain_pending_async_scans(self) -> list[dict]:
        """Hand the service's queued BG-scan descriptors to the caller.

        The list is consumed (emptied) so a second drain returns
        nothing. The API layer calls this AFTER its commit and then
        forwards each dict into ``BackgroundTasks.add_task(
        run_scan_in_background, **descriptor)``.
        """
        descriptors = self._pending_async_scans
        self._pending_async_scans = []
        return descriptors

    async def _dispatch_security_scan(
        self,
        *,
        trigger: str,
        created_by_id: str,
        owner_id: Optional[str],
        project_id: Optional[str],
        skill_id: Optional[uuid.UUID],
        name: str,
        description: str,
        content: str,
        tags: Optional[List[str]],
        license: Optional[str],
        files: Optional[List[Dict[str, Any]]],
        failure_mode: Literal["default", "fail_open", "fail_closed"] = "fail_open",
        enforce_write_policy: bool = True,
    ):
        """Run a scan either inline or as a background dispatch.

        Returns the same shape ``scan_for_write`` does — a
        :class:`SkillSecurityScan` or ``None`` — so existing call sites
        downstream don't need to change. The async path:

          - Returns ``None`` immediately.
          - Marks the skill row ``security_status='scanning'`` so the
            runtime gate blocks loads until the BG verdict lands.
          - Queues a descriptor on ``_pending_async_scans`` that the
            API layer drains and hands to FastAPI's BackgroundTasks.

        The async path is only available when ``skill_id`` is already
        known (i.e. update / file_* paths against an existing row).
        ``create_skill`` still runs sync — see the P2 plan's followup
        note about reordering the create transaction to enable async
        there too.
        """
        from app.joysafeter_domain.services.joysafeter_skill_security import (
            SkillSecurityService as _Sec,
        )
        from app.joysafeter_shared.config.settings import settings as _settings

        # P2.17: scanner disabled at deployment level — the inline path
        # below would return ``None`` cleanly, but the async path would
        # still mark the skill ``scanning`` and queue a descriptor that
        # ``run_scan_in_background`` immediately translates back to
        # ``not_scanned`` once it runs. That's wasted work AND a bigger
        # window where the row looks "in flight" — and pre-P2.16 the BG
        # task never even ran (no ``_flush_async_scans`` on create), so
        # the row stayed ``scanning`` forever. Short-circuit here so the
        # disabled-scanner path matches the inline contract: just return
        # None and let the caller proceed without any scan side-effect.
        if not _settings.skill_security_scan_enabled:
            return None

            # The "should this be async?" decision lives entirely in
            # SkillSecurityService so the threshold + bytes computation
            # has one canonical implementation.
        async_eligible = skill_id is not None and _Sec.should_scan_async(
            name=name,
            description=description,
            content=content,
            files=files,
        )

        if async_eligible:
            assert skill_id is not None  # implied by async_eligible
            await self.security_service.mark_scanning(skill_id)
            self._pending_async_scans.append(
                dict(
                    skill_id=skill_id,
                    trigger=trigger,
                    created_by_id=created_by_id,
                    owner_id=owner_id,
                    project_id=project_id,
                    name=name,
                    description=description,
                    content=content,
                    tags=tags,
                    license=license,
                    files=files,
                )
            )
            return None

            # Sync path — pre-P2.7 behavior.
        return await self.security_service.scan_for_write(
            enforce_write_policy=enforce_write_policy,
            failure_mode=failure_mode,
            trigger=trigger,
            created_by_id=created_by_id,
            owner_id=owner_id,
            project_id=project_id,
            skill_id=skill_id,
            name=name,
            description=description,
            content=content,
            tags=tags,
            license=license,
            files=files,
        )

    def _invalid_import_files_error(self, invalid_files: List[str]) -> InvalidRequestError:
        invalid_list = "\n".join(f"  - {file_name}" for file_name in invalid_files)
        return InvalidRequestError(
            f"The following files cannot be imported (binary files or system files):\n{invalid_list}\n\n"
            f"Skill import only supports text files (.py, .md, .json, .yaml, etc.)",
            code="SKILL_IMPORT_FILES_INVALID",
            data={"files": invalid_files},
        )

    def _is_skill_md_file(self, path: Optional[str], file_name: Optional[str]) -> bool:
        normalized_path = (path or "").replace("\\", "/").strip("/")
        normalized_name = (file_name or "").replace("\\", "/").rsplit("/", 1)[-1]
        return normalized_path.lower() == "skill.md" or normalized_name.lower() == "skill.md"

    def _skill_md_candidate_fields(
        self,
        skill: JoySafeterSkill,
        content: Optional[str],
    ) -> dict[str, Any]:
        fields: dict[str, Any] = {
            "name": skill.name,
            "description": skill.description,
            "content": skill.content,
            "tags": list(skill.tags or []),
            "license": skill.license,
        }
        if not content:
            return fields

        frontmatter, body = parse_skill_md(content)
        metadata = extract_metadata_from_frontmatter(frontmatter)
        if metadata.get("name"):
            fields["name"] = metadata["name"]
        if metadata.get("description"):
            fields["description"] = metadata["description"]
        if metadata.get("tags") and isinstance(metadata["tags"], list):
            fields["tags"] = metadata["tags"]
        if metadata.get("license"):
            fields["license"] = metadata["license"]
        if body:
            fields["content"] = body.strip()
        return fields

    def _apply_skill_md_content(self, skill: JoySafeterSkill, content: Optional[str]) -> None:
        if not content:
            return
        fields = self._skill_md_candidate_fields(skill, content)
        skill.name = fields["name"]
        skill.description = fields["description"]
        skill.content = fields["content"]
        skill.tags = fields["tags"]
        skill.license = fields["license"]

    async def list_skills(
        self,
        current_user_id: Optional[str] = None,
        include_public: bool = True,
        tags: Optional[List[str]] = None,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[List[JoySafeterSkill], bool]:
        """Get Skills list with cursor pagination.

        Each returned skill is annotated with ``latest_version`` — the most
        recently published version string, or ``None`` when the skill has
        never been published. Callers (e.g. the agent-builder skill picker)
        use this to hide draft-only skills that can't yet be referenced.
        """
        skills, has_more = await self.repo.list_by_user(
            user_id=current_user_id,
            include_public=include_public,
            tags=tags,
            project_id=project_id,
            org_id=org_id,
            limit=limit,
            after_id=after_id,
        )
        # Batch-annotate latest published version (single query, no N+1).
        ver_repo = SkillVersionRepository(self.db)
        latest_map = await ver_repo.latest_version_map([s.id for s in skills])
        for skill in skills:
            # ``latest_version`` is a request-scoped annotation declared as a
            # ClassVar on the model; set it per-instance via setattr so mypy
            # doesn't reject assigning to a class variable through an instance.
            setattr(skill, "latest_version", latest_map.get(skill.id))
        return skills, has_more

    async def get_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: Optional[str] = None,
    ) -> JoySafeterSkill:
        """Get Skill details"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill or not isinstance(skill, JoySafeterSkill):
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

            # Permission check: collaborator-aware
        if current_user_id:
            await check_skill_access(
                self.db,
                skill,
                current_user_id,
                JoySafeterCollaboratorRole.VIEWER,
                active_org_id=self._active_org_id,
            )
        else:
            # Anonymous read: only the ``public`` visibility tier opens
            # the row to a missing caller. Use the same fallback as
            # ``check_skill_access`` so a row written by a legacy
            # ``is_public=true`` writer still passes.
            effective = skill.visibility or ("public" if skill.is_public else "private")
            if effective != "public":
                raise AccessDeniedError(
                    "You don't have permission to access this skill",
                    code="SKILL_ACCESS_DENIED",
                )

                # Type assertion: get_with_files returns Optional[Skill], we've already checked it's not None
        skill = await self._attach_latest_version(skill)
        result = skill
        return result  # type: ignore

    async def get_skill_by_name(
        self,
        skill_name: str,
        current_user_id: Optional[str] = None,
    ) -> Optional[JoySafeterSkill]:
        """Get Skill by name (case-insensitive)

        Args:
            skill_name: Skill name
            current_user_id: Current user ID for permission check

        Returns:
            Skill object, returns None if not found or unauthorized
        """
        # Get all accessible skills. Pass ``org_id`` so the lookup
        # respects the caller's active org context — a user who's a
        # member of two orgs and shares a skill name between them
        # shouldn't get the wrong org's skill back here.
        all_skills, _ = await self.list_skills(
            current_user_id=current_user_id,
            include_public=True,
            org_id=self._active_org_id,
        )

        # Search by name (case-insensitive)
        for skill in all_skills:
            if skill.name.lower() == skill_name.lower():
                # Get complete information (including files)
                result = await self.repo.get_with_files(skill.id)
                return result if isinstance(result, JoySafeterSkill) else None

        return None

    async def create_skill(
        self,
        created_by_id: str,
        name: str,
        description: str,
        content: str,
        tags: Optional[List[str]] = None,
        source_type: str = "local",
        source_url: Optional[str] = None,
        root_path: Optional[str] = None,
        owner_id: Optional[str] = None,
        is_public: bool = False,
        visibility: Optional[str] = None,
        license: Optional[str] = None,
        files: Optional[List[Dict[str, Any]]] = None,
        project_id: Optional[str] = None,
    ) -> JoySafeterSkill:
        """Create Skill

        If files contain a SKILL.md file with YAML frontmatter, metadata
        (tags, license, compatibility, etc.) will be extracted from it.
        Name and description from frontmatter are only used as fallbacks
        when the caller does not provide them.
        """
        # If owner_id is not specified, use creator ID
        if owner_id is None:
            owner_id = created_by_id

            # Initialize new fields per Agent Skills specification
        compatibility = None
        skill_metadata = {}
        allowed_tools = []

        # Parse SKILL.md frontmatter if present to sync name/description
        if files:
            skill_md_file = next(
                (f for f in files if f.get("path") == "SKILL.md" or f.get("file_name") == "SKILL.md"), None
            )
            if skill_md_file and skill_md_file.get("content"):
                frontmatter, body = parse_skill_md(skill_md_file["content"])
                # Extract all metadata using extract_metadata_from_frontmatter
                metadata = extract_metadata_from_frontmatter(frontmatter)

                # Caller-provided values take priority over frontmatter.
                if not name and metadata.get("name"):
                    name = metadata["name"]
                if not description and metadata.get("description"):
                    description = metadata["description"]

                    # Extract additional metadata from frontmatter
                if metadata.get("tags") and isinstance(metadata["tags"], list):
                    tags = metadata["tags"]
                if metadata.get("license"):
                    license = metadata["license"]

                    # Extract new fields per Agent Skills specification
                compatibility = metadata.get("compatibility")
                skill_metadata = metadata.get("metadata", {})
                allowed_tools = metadata.get("allowed_tools", [])

                # Store the markdown body as content
                content = body.strip() if body else content

                # Log warnings for uncommon file extensions (but don't reject)
            for file_data in files:
                file_path = file_data.get("path", "")
                if file_path:
                    is_common, warning = validate_file_extension(file_path)
                    if warning:
                        # Just log the warning, don't reject
                        logger.warning(f"Skill file warning: {warning}")

                        # Validate skill name per Agent Skills specification
        is_valid, error = validate_skill_name(name)
        if not is_valid:
            logger.warning(f"Invalid skill name rejected: {name!r} — {error}")
            raise InvalidRequestError(
                f"Invalid skill name: {error}",
                code="SKILL_NAME_INVALID",
                data={"validation_error": error, "name": name},
            )

            # Validate and truncate description per Agent Skills specification
        is_valid, error = validate_skill_description(description)
        if not is_valid:
            # Truncate if too long (warn but continue)
            logger.warning(f"Skill description exceeds 1024 characters, truncating: {error}")
            description = truncate_description(description)

            # Validate compatibility if provided
        if compatibility is not None:
            is_valid, error = validate_compatibility(compatibility)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill compatibility exceeds 500 characters, truncating: {error}")
                compatibility = truncate_compatibility(compatibility)

                # Check if Skill with same name exists (same owner)
        existing = await self.repo.get_by_name_and_owner(name, owner_id)
        if existing:
            raise InvalidRequestError(
                f"Skill name '{name}' already exists for this owner",
                code="SKILL_NAME_ALREADY_EXISTS",
                data={"name": name},
            )

        if files:
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                file_content_raw = file_data.get("content")
                file_content_val: Optional[str] = (
                    file_content_raw
                    if isinstance(file_content_raw, (str, type(None)))
                    else str(file_content_raw)
                    if file_content_raw is not None
                    else None
                )
                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue
                if file_content_val is not None:
                    is_valid, error_msg = is_valid_text_content(file_content_val)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        security_scan = await self.security_service.scan_for_write(
            failure_mode="fail_open",
            trigger="create",
            created_by_id=created_by_id,
            owner_id=owner_id,
            project_id=project_id,
            skill_id=None,
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            license=license,
            files=files,
        )

        # Dual-write: ``visibility`` is now the canonical column.
        # Precedence rule:
        #   1. Explicit ``visibility`` from the caller (P2.8) wins.
        #   2. Legacy callers passing only ``is_public`` derive
        #      ``visibility`` from ``is_public + project_id`` — mirrors
        #      the 20260625_000003 backfill so a client that hasn't
        #      adopted ``visibility`` yet gets the obvious mapping.
        # We also keep ``is_public`` in sync so any reader still on
        # the old column sees a consistent value.
        if visibility is not None:
            visibility_value = visibility
            is_public = visibility == "public"
        elif is_public:
            visibility_value = "public"
        elif project_id is not None:
            visibility_value = "project"
        else:
            visibility_value = "private"

        skill = JoySafeterSkill(
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            source_type=source_type,
            source_url=source_url,
            root_path=root_path,
            owner_id=owner_id,
            created_by_id=created_by_id,
            is_public=is_public,
            visibility=visibility_value,
            license=license,
            compatibility=compatibility,
            meta_data=skill_metadata,
            allowed_tools=allowed_tools,
            project_id=project_id,
        )
        self.db.add(skill)
        await self.db.flush()
        await self.db.refresh(skill)
        if security_scan is not None:
            security_scan.skill_id = skill.id
            self.security_service.apply_latest_scan(skill, security_scan)

            # Create associated files
        if files:
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                file_content_raw = file_data.get("content")
                file_content_val = (
                    file_content_raw
                    if isinstance(file_content_raw, (str, type(None)))
                    else str(file_content_raw)
                    if file_content_raw is not None
                    else None
                )

                # Check if it's a system file
                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue

                    # Validate content if provided
                if file_content_val is not None:
                    is_valid, error_msg = is_valid_text_content(file_content_val)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
                        continue

                        # file_content_val can be None, but SkillFile.content might require str
                file_content: str = file_content_val if file_content_val is not None else ""
                file_obj = JoySafeterSkillFile(
                    skill_id=skill.id,
                    path=file_path,
                    file_name=file_name,
                    file_type=file_data.get("file_type", ""),
                    content=file_content,
                    storage_type=file_data.get("storage_type", "database"),
                    storage_key=file_data.get("storage_key"),
                    size=file_data.get("size", 0),
                )
                self.db.add(file_obj)

                # If there are invalid files, raise an error
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        await self.db.commit()
        await self.db.refresh(skill)
        result = skill
        return result  # type: ignore

    async def update_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        content: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source_type: Optional[str] = None,
        source_url: Optional[str] = None,
        root_path: Optional[str] = None,
        owner_id: Optional[str] = None,
        is_public: Optional[bool] = None,
        visibility: Optional[str] = None,
        license: Optional[str] = None,
        compatibility: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        allowed_tools: Optional[List[str]] = None,
        files: Optional[List[Dict[str, Any]]] = None,
    ) -> JoySafeterSkill:
        """Update Skill

        If files are provided, they will replace all existing files for this skill.
        """
        skill = await self.repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

            # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.EDITOR,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Parse SKILL.md frontmatter if files contain SKILL.md
        if files:
            skill_md_file = next(
                (f for f in files if f.get("path") == "SKILL.md" or f.get("file_name") == "SKILL.md"), None
            )
            if skill_md_file and skill_md_file.get("content"):
                frontmatter, body = parse_skill_md(skill_md_file["content"])
                # Extract all metadata using extract_metadata_from_frontmatter
                metadata_dict = extract_metadata_from_frontmatter(frontmatter)

                # Override fields from frontmatter if not explicitly provided
                if metadata_dict.get("name") and name is None:
                    name = metadata_dict["name"]
                if metadata_dict.get("description") and description is None:
                    description = metadata_dict["description"]
                if metadata_dict.get("tags") and isinstance(metadata_dict["tags"], list) and tags is None:
                    tags = metadata_dict["tags"]
                if metadata_dict.get("license") and license is None:
                    license = metadata_dict["license"]
                if metadata_dict.get("compatibility") is not None and compatibility is None:
                    compatibility = metadata_dict["compatibility"]
                if metadata_dict.get("metadata") and metadata is None:
                    metadata = metadata_dict["metadata"]
                if metadata_dict.get("allowed_tools") and allowed_tools is None:
                    allowed_tools = metadata_dict["allowed_tools"]

                    # Store the markdown body as content if not explicitly provided
                if content is None:
                    content = body.strip() if body else None

                    # Log warnings for uncommon file extensions (but don't reject)
            for file_data in files:
                file_path = file_data.get("path", "")
                if file_path:
                    is_common, warning = validate_file_extension(file_path)
                    if warning:
                        logger.warning(f"Skill file warning: {warning}")

        proposed_name = skill.name if name is None else name
        proposed_description = skill.description if description is None else description
        proposed_content = skill.content if content is None else content
        proposed_tags = skill.tags if tags is None else tags
        proposed_source_type = skill.source_type if source_type is None else source_type
        proposed_source_url = skill.source_url if source_url is None else source_url
        proposed_root_path = skill.root_path if root_path is None else root_path
        proposed_owner_id = skill.owner_id if owner_id is None else owner_id
        proposed_is_public = skill.is_public if is_public is None else is_public
        proposed_license = skill.license if license is None else license
        proposed_compatibility = skill.compatibility if compatibility is None else compatibility
        proposed_metadata = skill.meta_data
        proposed_allowed_tools = skill.allowed_tools

        # ── Privilege gates run BEFORE any write or scan ──
        # P2.13: the ownership and visibility gates were originally
        # placed after the security scan dispatch. That meant a
        # rejected PUT still left an audit row in
        # ``joysafeter_skill_security_scans`` claiming the spoofed
        # ``owner_id`` / ``created_by_id`` had legitimately scanned
        # the skill — useful telemetry for an attacker probing what
        # private content trips which scanner rule, and noise in the
        # audit log. Running the gates first means no side effects
        # of any kind escape the request when the caller is unauthorized.
        owner_before_change = skill.owner_id
        if owner_id is not None and proposed_owner_id != owner_before_change:
            if owner_before_change != current_user_id:
                raise AccessDeniedError(
                    "Only the skill owner can transfer ownership.",
                    code="SKILL_OWNERSHIP_OWNER_ONLY",
                    data={
                        "skill_id": str(skill.id),
                        "user_id": current_user_id,
                        "current_owner_id": owner_before_change,
                        "proposed_owner_id": proposed_owner_id,
                    },
                )

        current_visibility = skill.visibility or ("public" if skill.is_public else "private")
        # P2.15: ``is_public`` is the legacy boolean that the dual-write
        # block below (see ~line 778-783) still translates back into a
        # ``visibility`` tier. So a non-owner admin collaborator who sends
        # only ``{"is_public": true}`` would have skipped the owner-only
        # gate (because ``visibility`` stayed None and ``target_visibility``
        # stayed equal to ``current_visibility``) yet still escalate the
        # skill to ``public`` once line 778 ran. Compute the effective
        # target the same way the dual-write block will to keep the gate
        # in lockstep with the actual mutation.
        if visibility is not None:
            target_visibility = visibility
        elif is_public is not None:
            if is_public:
                target_visibility = "public"
            elif skill.project_id is not None:
                target_visibility = "project"
            else:
                target_visibility = "private"
        else:
            target_visibility = current_visibility
        visibility_changes = current_visibility != target_visibility
        if visibility_changes and owner_before_change != current_user_id:
            raise AccessDeniedError(
                "Only the skill owner can change the visibility tier. "
                "Admin collaborators may edit content but cannot retier "
                "who the skill is shared with.",
                code="SKILL_VISIBILITY_OWNER_ONLY",
                data={
                    "skill_id": str(skill.id),
                    "user_id": current_user_id,
                    "from_visibility": current_visibility,
                    "to_visibility": target_visibility,
                },
            )

            # Validate name if provided
        if name and name != skill.name:
            is_valid, error = validate_skill_name(name)
            if not is_valid:
                logger.warning(f"Invalid skill name rejected: {name!r} — {error}")
                raise InvalidRequestError(
                    f"Invalid skill name: {error}",
                    code="SKILL_NAME_INVALID",
                    data={"validation_error": error, "name": name},
                )
            existing = await self.repo.get_by_name_and_owner(name, skill.owner_id)
            if existing:
                raise InvalidRequestError(
                    f"Skill name '{name}' already exists for this owner",
                    code="SKILL_NAME_ALREADY_EXISTS",
                    data={"name": name},
                )

                # Validate description if provided
        if description is not None:
            is_valid, error = validate_skill_description(description)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill description exceeds 1024 characters, truncating: {error}")
                proposed_description = truncate_description(description)

                # Validate compatibility if provided
        if compatibility is not None:
            is_valid, error = validate_compatibility(compatibility)
            if not is_valid:
                # Truncate if too long (warn but continue)
                logger.warning(f"Skill compatibility exceeds 500 characters, truncating: {error}")
                proposed_compatibility = truncate_compatibility(compatibility)

                # Prepare metadata if provided
        if metadata is not None:
            # Ensure all values are strings (per spec)
            if isinstance(metadata, dict):
                proposed_metadata = {k: str(v) for k, v in metadata.items() if isinstance(k, str)}
            else:
                proposed_metadata = {}

                # Prepare allowed_tools if provided
        if allowed_tools is not None:
            if isinstance(allowed_tools, list):
                proposed_allowed_tools = allowed_tools
            else:
                proposed_allowed_tools = []

        proposed_files = files if files is not None else self.security_service.files_from_skill(skill)
        if files is not None:
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                file_content = file_data.get("content")

                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue

                if file_content is not None:
                    is_valid, error_msg = is_valid_text_content(file_content)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
                        continue
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        # Only the skill's *content* is security-relevant: the SKILL.md body
        # and the attached files carry the code/instructions the scanner
        # inspects. Pure metadata edits (name / description / tags / license /
        # visibility) don't change what the skill *does*, so re-running the
        # (potentially slow, inline-LLM) scanner on every such save is wasted
        # work — and it blocked the "Save" button for seconds on skills small
        # enough to fall under the async threshold. Skip the scan entirely
        # when neither the SKILL.md content nor the file set changed; the
        # skill keeps its existing security verdict untouched.
        content_changed = content is not None and proposed_content != skill.content
        files_changed = files is not None
        if content_changed or files_changed:
            security_scan = await self._dispatch_security_scan(
                trigger="update",
                created_by_id=current_user_id,
                owner_id=proposed_owner_id,
                project_id=skill.project_id,
                skill_id=skill.id,
                name=proposed_name,
                description=proposed_description,
                content=proposed_content,
                tags=proposed_tags or [],
                license=proposed_license,
                files=proposed_files,
            )
        else:
            security_scan = None

        skill.name = proposed_name
        skill.description = proposed_description
        skill.content = proposed_content
        skill.tags = proposed_tags or []
        skill.source_type = proposed_source_type
        skill.source_url = proposed_source_url
        skill.root_path = proposed_root_path
        # The ownership and visibility gates ran at the top of the
        # function (P2.13) so we don't pay any side effects of an
        # unauthorized call. By the time control reaches here, both
        # mutations are pre-approved.
        skill.owner_id = proposed_owner_id
        skill.is_public = proposed_is_public
        # Dual-write visibility (see ``create_skill`` for the mapping
        # rationale). Precedence: explicit ``visibility`` from the caller
        # wins; otherwise derive from is_public + project_id, but only
        # when the caller actually moved the boolean — an update that
        # only renames a skill must not accidentally retier its share
        # surface.
        if visibility is not None:
            skill.visibility = visibility
            # Keep the legacy boolean in sync for any reader still on
            # the old column.
            skill.is_public = visibility == "public"
        elif is_public is not None:
            if proposed_is_public:
                skill.visibility = "public"
            elif skill.project_id is not None:
                skill.visibility = "project"
            else:
                skill.visibility = "private"
        skill.license = proposed_license
        skill.compatibility = proposed_compatibility
        skill.meta_data = proposed_metadata or {}
        skill.allowed_tools = proposed_allowed_tools or []

        # Handle file updates - replace all files if files are provided
        if files is not None:
            # Delete existing files
            await self.file_repo.delete_by_skill(skill_id)

            # Create new files
            invalid_files = []
            for file_data in files:
                file_path = file_data.get("path", "")
                file_name = file_data.get("file_name", "")
                content = file_data.get("content")

                # Check if it's a system file
                if is_system_file(file_path) or is_system_file(file_name):
                    invalid_files.append(f"{file_path} (system file)")
                    continue

                    # Validate content if provided
                if content is not None:
                    is_valid, error_msg = is_valid_text_content(content)
                    if not is_valid:
                        invalid_files.append(f"{file_path} ({error_msg})")
                        continue

                file_obj = JoySafeterSkillFile(
                    skill_id=skill_id,
                    path=file_path,
                    file_name=file_name,
                    file_type=file_data.get("file_type", ""),
                    content=content,
                    storage_type=file_data.get("storage_type", "database"),
                    storage_key=file_data.get("storage_key"),
                    size=file_data.get("size", 0),
                )
                self.db.add(file_obj)

                # If there are invalid files, raise an error
            if invalid_files:
                raise self._invalid_import_files_error(invalid_files)

        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)

        await self.db.commit()
        await self.db.refresh(skill)
        result = skill
        return result  # type: ignore

    async def delete_skill(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
    ) -> None:
        """Delete Skill"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

            # Permission check: Only owner can delete
        if skill.owner_id != current_user_id:
            raise AccessDeniedError("Only the owner can delete a skill", code="SKILL_DELETE_FORBIDDEN")
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.ADMIN,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

            # Delete associated files
        await self.file_repo.delete_by_skill(skill_id)

        # Delete Skill
        await self.repo.delete(skill_id)
        await self.db.commit()

    async def add_file(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        path: str,
        file_name: str,
        file_type: str,
        content: Optional[str] = None,
        storage_type: str = "database",
        storage_key: Optional[str] = None,
        size: int = 0,
    ) -> JoySafeterSkillFile:
        """Add file to Skill"""
        skill = await self.repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})

            # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.EDITOR,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Check if it's a system file
        if is_system_file(path) or is_system_file(file_name):
            raise InvalidRequestError(
                f"File '{path}' is a system file and cannot be imported",
                code="SKILL_SYSTEM_FILE_IMPORT_FORBIDDEN",
                data={"path": path},
            )

            # Validate content if provided
        if content is not None:
            is_valid, error_msg = is_valid_text_content(content)
            if not is_valid:
                raise InvalidRequestError(
                    f"File '{path}' {error_msg}. Skill import only supports text files (.py, .md, .json, .yaml, etc.)",
                    code="SKILL_FILE_CONTENT_INVALID",
                    data={"path": path},
                )

                # Log warning for uncommon file extensions (but don't reject)
        if path:
            is_common, warning = validate_file_extension(path)
            if warning:
                logger.warning(f"Skill file warning: {warning}")

        # Newly-created files start empty — both the ``.gitkeep`` a folder
        # create adds, and any regular file the user creates before typing
        # into it. Empty content has nothing to scan, so a full security scan
        # (which can take a minute of LLM analysis and flips the skill to
        # ``scanning``) is pure waste. Skip the scan when the added file is
        # empty; the scan runs later on ``update_file`` once the user saves
        # real content.
        is_empty_new_file = not (content or "").strip()

        if is_empty_new_file:
            security_scan = None
        else:
            proposed_files = self.security_service.files_from_skill(skill)
            proposed_files.append(
                {
                    "path": path,
                    "file_name": file_name,
                    "file_type": file_type,
                    "content": content or "",
                    "storage_type": storage_type,
                    "storage_key": storage_key,
                    "size": size,
                }
            )
            scan_fields = (
                self._skill_md_candidate_fields(skill, content)
                if self._is_skill_md_file(path, file_name)
                else {
                    "name": skill.name,
                    "description": skill.description,
                    "content": skill.content,
                    "tags": list(skill.tags or []),
                    "license": skill.license,
                }
            )
            security_scan = await self._dispatch_security_scan(
                trigger="file_add",
                created_by_id=current_user_id,
                owner_id=skill.owner_id,
                project_id=skill.project_id,
                skill_id=skill.id,
                name=scan_fields["name"],
                description=scan_fields["description"],
                content=scan_fields["content"],
                tags=scan_fields["tags"],
                license=scan_fields["license"],
                files=proposed_files,
            )

        file_obj = JoySafeterSkillFile(
            skill_id=skill_id,
            path=path,
            file_name=file_name,
            file_type=file_type,
            content=content,
            storage_type=storage_type,
            storage_key=storage_key,
            size=size,
        )
        self.db.add(file_obj)
        if self._is_skill_md_file(path, file_name):
            self._apply_skill_md_content(skill, content)
        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)
        await self.db.commit()
        await self.db.refresh(file_obj)

        return file_obj

    async def delete_file(
        self,
        file_id: uuid.UUID,
        current_user_id: str,
        expected_skill_id: Optional[uuid.UUID] = None,
    ) -> None:
        """Delete file"""
        file_obj = await self.file_repo.get(file_id)
        if not file_obj:
            raise NotFoundError("Skill file not found", code="SKILL_FILE_NOT_FOUND", data={"file_id": str(file_id)})

            # See ``update_file`` for the rationale on this URL-consistency
            # check — same defense-in-depth gate.
        if expected_skill_id is not None and file_obj.skill_id != expected_skill_id:
            raise NotFoundError(
                "Skill file not found",
                code="SKILL_FILE_NOT_FOUND",
                data={"file_id": str(file_id), "skill_id": str(expected_skill_id)},
            )

        skill = await self.repo.get_with_files(file_obj.skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(file_obj.skill_id)})

            # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.EDITOR,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Deleting an empty file (a ``.gitkeep`` placeholder, or a file the
        # user created but never wrote into) removes nothing scannable — the
        # remaining content is unchanged — so a re-scan is pure waste. Deleting
        # a file that HAD content does change the scannable surface, so it
        # still scans.
        deleted_was_empty = not (file_obj.content or "").strip()

        if deleted_was_empty:
            security_scan = None
        else:
            proposed_files = [
                {
                    "path": existing_file.path,
                    "file_name": existing_file.file_name,
                    "file_type": existing_file.file_type,
                    "content": existing_file.content or "",
                    "storage_type": existing_file.storage_type,
                    "storage_key": existing_file.storage_key,
                    "size": existing_file.size,
                }
                for existing_file in (skill.files or [])
                if existing_file.id != file_obj.id
            ]
            security_scan = await self._dispatch_security_scan(
                enforce_write_policy=False,
                trigger="file_delete",
                created_by_id=current_user_id,
                owner_id=skill.owner_id,
                project_id=skill.project_id,
                skill_id=skill.id,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                tags=list(skill.tags or []),
                license=skill.license,
                files=proposed_files,
            )

        await self.file_repo.delete(file_id)
        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)
        await self.db.commit()

    async def update_file(
        self,
        file_id: uuid.UUID,
        current_user_id: str,
        content: Optional[str] = None,
        path: Optional[str] = None,
        file_name: Optional[str] = None,
        expected_skill_id: Optional[uuid.UUID] = None,
    ) -> JoySafeterSkillFile:
        """Update file content"""
        file_obj = await self.file_repo.get(file_id)
        if not file_obj:
            raise NotFoundError("Skill file not found", code="SKILL_FILE_NOT_FOUND", data={"file_id": str(file_id)})

            # API contract: the caller passes the file's skill_id in the
            # URL path. Reject when the URL's skill_id doesn't match the
            # file's real owner. This is defense-in-depth — the access
            # check below still works correctly via ``file_obj.skill_id``,
            # but a mismatched URL almost always means the client got
            # confused about which skill they're editing and the safest
            # answer is a 404 so they don't silently mutate a different
            # skill's content.
        if expected_skill_id is not None and file_obj.skill_id != expected_skill_id:
            raise NotFoundError(
                "Skill file not found",
                code="SKILL_FILE_NOT_FOUND",
                data={"file_id": str(file_id), "skill_id": str(expected_skill_id)},
            )

        skill = await self.repo.get_with_files(file_obj.skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(file_obj.skill_id)})

            # Permission check: collaborator-aware (editor role)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.EDITOR,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Check if it's a system file (if path is being updated)
        if path is not None:
            if is_system_file(path) or is_system_file(file_obj.file_name):
                raise InvalidRequestError(
                    f"File '{path}' is a system file and cannot be imported",
                    code="SKILL_SYSTEM_FILE_IMPORT_FORBIDDEN",
                    data={"path": path},
                )

                # Log warning for uncommon file extensions (but don't reject)
            is_common, warning = validate_file_extension(path)
            if warning:
                logger.warning(f"Skill file warning: {warning}")

        if content is not None:
            # Validate content
            is_valid, error_msg = is_valid_text_content(content)
            if not is_valid:
                raise InvalidRequestError(
                    f"File '{file_obj.path}' {error_msg}. Skill import only supports text files (.py, .md, .json, .yaml, etc.)",
                    code="SKILL_FILE_CONTENT_INVALID",
                    data={"path": file_obj.path},
                )

        proposed_path = file_obj.path if path is None else path
        proposed_file_name = file_obj.file_name if file_name is None else file_name
        proposed_content = file_obj.content if content is None else content
        proposed_files = []
        for existing_file in skill.files or []:
            if existing_file.id == file_obj.id:
                proposed_files.append(
                    {
                        "path": proposed_path,
                        "file_name": proposed_file_name,
                        "file_type": existing_file.file_type,
                        "content": proposed_content or "",
                        "storage_type": existing_file.storage_type,
                        "storage_key": existing_file.storage_key,
                        "size": len(proposed_content) if proposed_content else 0,
                    }
                )
            else:
                proposed_files.append(
                    {
                        "path": existing_file.path,
                        "file_name": existing_file.file_name,
                        "file_type": existing_file.file_type,
                        "content": existing_file.content or "",
                        "storage_type": existing_file.storage_type,
                        "storage_key": existing_file.storage_key,
                        "size": existing_file.size,
                    }
                )
        scan_fields = (
            self._skill_md_candidate_fields(skill, proposed_content)
            if self._is_skill_md_file(proposed_path, proposed_file_name)
            else {
                "name": skill.name,
                "description": skill.description,
                "content": skill.content,
                "tags": list(skill.tags or []),
                "license": skill.license,
            }
        )
        security_scan = await self._dispatch_security_scan(
            trigger="file_update",
            created_by_id=current_user_id,
            owner_id=skill.owner_id,
            project_id=skill.project_id,
            skill_id=skill.id,
            name=scan_fields["name"],
            description=scan_fields["description"],
            content=scan_fields["content"],
            tags=scan_fields["tags"],
            license=scan_fields["license"],
            files=proposed_files,
        )

        if content is not None:
            file_obj.content = content
            file_obj.size = len(content) if content else 0
        if path is not None:
            file_obj.path = path
        if file_name is not None:
            file_obj.file_name = file_name

        if self._is_skill_md_file(file_obj.path, file_obj.file_name):
            self._apply_skill_md_content(skill, file_obj.content)
        if security_scan is not None:
            self.security_service.apply_latest_scan(skill, security_scan)
        await self.db.commit()
        await self.db.refresh(file_obj)

        # Type assertion: refresh updates the object in place
        return file_obj  # type: ignore

    async def _sync_skill_from_skill_md(
        self,
        skill: JoySafeterSkill,
        content: Optional[str],
    ) -> None:
        """Sync skill metadata from SKILL.md frontmatter.

        Args:
            skill: The skill to update
            content: The SKILL.md content with YAML frontmatter
        """
        if not content:
            return

        self._apply_skill_md_content(skill, content)
        await self.db.commit()
        await self.db.refresh(skill)

    async def import_skill_from_directory(
        self, skill_dir: str, owner_id: str, is_public: bool = False
    ) -> JoySafeterSkill:
        """Import Skill from directory

        Args:
            skill_dir: Skill directory path (containing SKILL.md)
            owner_id: Owner ID

        Returns:
            Created or updated Skill object
        """
        from pathlib import Path

        from app.joysafeter_shared.skill.yaml_parser import extract_metadata_from_frontmatter, parse_skill_md

        skill_path = Path(skill_dir)
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill directory not found: {skill_dir}")

            # Find SKILL.md
        skill_md_path = skill_path / "SKILL.md"
        if not skill_md_path.exists():
            # Try lowercase
            skill_md_path = skill_path / "skill.md"

        if not skill_md_path.exists():
            raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

            # Read SKILL.md
        with open(skill_md_path, "r", encoding="utf-8") as f:
            content = f.read()

            # Parse metadata
        frontmatter, body = parse_skill_md(content)
        metadata = extract_metadata_from_frontmatter(frontmatter)

        name = metadata.get("name", skill_path.name)
        description = metadata.get("description", "")

        # Prepare file list
        files = []

        # Add SKILL.md
        files.append({"path": "SKILL.md", "file_name": "SKILL.md", "content": content, "file_type": "markdown"})

        # Recursively read other files
        for file_path in skill_path.rglob("*"):
            if file_path.is_file() and file_path.name.lower() != "skill.md" and not file_path.name.startswith("."):
                try:
                    rel_path = file_path.relative_to(skill_path)

                    # Simple binary file check (try reading as utf-8)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            file_content = f.read()

                        files.append(
                            {
                                "path": str(rel_path),
                                "file_name": file_path.name,
                                "content": file_content,
                                "file_type": self._detect_file_type(file_path),
                            }
                        )
                    except UnicodeDecodeError:
                        # Skip binary files
                        continue
                except Exception:
                    continue

                    # Check if exists
        try:
            existing_skill = await self.get_skill_by_name(name, current_user_id=owner_id)
        except Exception:
            existing_skill = None

        if existing_skill:
            return await self.update_skill(
                skill_id=existing_skill.id,
                current_user_id=owner_id,
                name=name,
                description=description,
                files=files,
                is_public=is_public,
            )
        else:
            return await self.create_skill(
                created_by_id=owner_id,
                name=name,
                description=description,
                content=body,
                files=files,
                owner_id=owner_id,
                is_public=is_public,
            )

    async def list_security_scans(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ):
        """List security scan history for a skill."""
        return await self.security_service.list_scans(skill_id, current_user_id, limit=limit, after_id=after_id)

    async def get_latest_security_scan(self, skill_id: uuid.UUID, current_user_id: str):
        """Get latest security scan for a skill."""
        return await self.security_service.get_latest_scan(skill_id, current_user_id)

    async def get_security_scan(self, scan_id: uuid.UUID, current_user_id: str):
        """Get a security scan by id."""
        return await self.security_service.get_scan(scan_id, current_user_id)

    async def rescan_skill(self, skill_id: uuid.UUID, current_user_id: str):
        """Run a manual security rescan for persisted skill content."""
        return await self.security_service.rescan_existing_skill(skill_id, current_user_id)

    async def rescan_skill_async(self, skill_id: uuid.UUID, current_user_id: str):
        """Dispatch a manual rescan as a background task and return immediately.

        Manual rescans always defer (unlike write-path scans that defer only
        above a size threshold): with LLM semantic analysis enabled a scan
        routinely takes 30-60s, far longer than any reasonable HTTP timeout.
        So we mark the skill ``scanning``, queue the work on
        ``_pending_async_scans`` (drained by the endpoint into FastAPI's
        BackgroundTasks), and return the current scan row so the client can
        poll ``security-scans/latest`` until the verdict lands.

        Mirrors ``_dispatch_security_scan``'s async branch + the permission
        + fallback bookkeeping from ``rescan_existing_skill``.
        """
        from app.joysafeter_domain.models.joysafeter_skill import (
            JoySafeterSkillSecurityScan,
        )
        from app.joysafeter_domain.services.joysafeter_skill_security import (
            JoySafeterCollaboratorRole,
        )
        from app.joysafeter_shared.common.skill_permissions import check_skill_access
        from app.joysafeter_shared.config.settings import settings as _settings

        sec = self.security_service
        skill = await sec.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            JoySafeterCollaboratorRole.EDITOR,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Scanner disabled at deployment level: nothing to do, fall back to
        # the synchronous path which cleanly returns a not_scanned row.
        if not _settings.skill_security_scan_enabled:
            return await sec.rescan_existing_skill(skill_id, current_user_id)

        files = sec.files_from_skill(skill)
        await sec.mark_scanning(skill.id)
        self._pending_async_scans.append(
            dict(
                skill_id=skill.id,
                trigger="manual",
                created_by_id=current_user_id,
                owner_id=skill.owner_id,
                project_id=skill.project_id,
                name=skill.name,
                description=skill.description,
                content=skill.content,
                tags=list(skill.tags or []),
                license=skill.license,
                files=files,
            )
        )
        await self.db.commit()

        # Return the latest scan row (now reflecting scanning state) so the
        # client gets a 200 with something to poll against. If the skill has
        # never been scanned, synthesize a lightweight scanning placeholder.
        latest = await sec.repo.get_latest_by_skill(skill.id)
        if latest is not None:
            return latest
        placeholder = JoySafeterSkillSecurityScan(
            skill_id=skill.id,
            project_id=skill.project_id,
            owner_id=skill.owner_id,
            created_by_id=current_user_id,
            trigger="manual",
            target_name=skill.name,
            target_hash="",
            scanner="skillspector",
            status="scanning",
            score=None,
            severity=None,
            recommendation=None,
            report=None,
        )
        self.db.add(placeholder)
        await self.db.commit()
        await self.db.refresh(placeholder)
        return placeholder

    def _detect_file_type(self, file_path: Union[str, Path]) -> str:
        """Simple file type detection"""
        if isinstance(file_path, str):
            file_path = Path(file_path)

        suffix = file_path.suffix.lower()
        if suffix == ".py":
            return "python"
        elif suffix == ".md":
            return "markdown"
        elif suffix == ".json":
            return "json"
        elif suffix == ".yaml" or suffix == ".yml":
            return "yaml"
        else:
            return "text"

    async def _attach_latest_version(self, skill):
        """Attach latest_version string to skill for API response."""
        ver_repo = SkillVersionRepository(self.db)
        latest = await ver_repo.get_latest(skill.id)
        skill.latest_version = latest.version if latest else None
        return skill
