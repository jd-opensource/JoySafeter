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

Every transition is gated by the caller's project capability on the skill
(via ``check_skill_access``): there is no owner special-case and no per-skill
collaborator role — write/admin comes solely from the project role.

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
    JoySafeterSkillLifecycleStatus,
    JoySafeterSkillVisibility,
)
from app.joysafeter_domain.repositories.joysafeter_skill import SkillRepository
from app.joysafeter_shared.common.app_errors import (
    InvalidRequestError,
    NotFoundError,
)
from app.joysafeter_shared.common.joysafeter_auth.context import (
    JoySafeterRole,
    ProjectCapability,
)
from app.joysafeter_shared.common.skill_permissions import check_skill_access, resolve_skill_org_id

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

    # Class-level default so bare ``__new__``-constructed test harnesses
    # (which set only the fields they exercise) still resolve a sane org
    # role when they stub ``check_skill_access``.
    _caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER

    def __init__(
        self,
        db: AsyncSession,
        *,
        active_org_id: Optional[str] = None,
        caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER,
    ):
        self.db = db
        self.skill_repo = SkillRepository(db)
        # P2.9: active org for strict isolation in ``check_skill_access``.
        # When the API layer constructs this service from a
        # JoySafeterAuthContext, the org id is threaded through so a
        # multi-org admin can't fire transitions from a different org
        # context. ``None`` falls back to pre-P2.9 behavior.
        self._active_org_id = active_org_id
        # Single-axis redesign: the caller's org role is threaded through
        # to ``check_skill_access`` so an org super-user resolves to ADMIN
        # capability. ``MEMBER`` is the safe default for internal callers.
        self._caller_org_role = caller_org_role

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
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError(
                "Skill not found",
                code="SKILL_NOT_FOUND",
                data={"skill_id": str(skill_id)},
            )

        # Authorization: lifecycle transitions (submit/approve/reject/archive/
        # unarchive/reopen) require ProjectCapability.ADMIN — a stricter gate
        # than ordinary content writes (create/edit files use WRITE). Approving
        # or publishing a skill is a higher-privilege act than editing it.
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.ADMIN,
            caller_org_role=self._caller_org_role,
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

        if to_status == JoySafeterSkillLifecycleStatus.APPROVED.value:
            from app.joysafeter_domain.services.joysafeter_skill_security import scan_ok
            from app.joysafeter_shared.config import settings

            if settings.skill_security_scan_enabled:
                scan_ready, reason = scan_ok(skill)
                if not scan_ready:
                    raise InvalidRequestError(
                        "Skill must pass security scan before entering approved state.",
                        code="SKILL_LIFECYCLE_NOT_RUNTIME_READY",
                        data={"skill_id": str(skill_id), "from_status": from_status, "reason": reason},
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
    _caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER

    def __init__(
        self,
        db,
        *,
        active_org_id: Optional[str] = None,
        caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER,
    ):
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
        self._caller_org_role = caller_org_role

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
            ProjectCapability.ADMIN,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)

        # Runtime-readiness gate — publishing a snapshot that no agent can
        # load creates a dead version and breaks the product contract between
        # Skills, Agent picker, and orchestrator. Keep the historical
        # ``SKILL_SECURITY_BLOCKED`` code for the high-risk verdict, but fail
        # every other runtime-ineligible state with a precise reason.
        # When security scanning is disabled globally, skip all scan gates.
        from app.joysafeter_shared.config import settings as app_settings

        if app_settings.skill_security_scan_enabled:
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
            from app.joysafeter_domain.services.joysafeter_skill_security import is_skill_usable

            usable, reason = is_skill_usable(skill)
            if not usable:
                raise InvalidRequestError(
                    "Skill is not runtime-ready and cannot be published.",
                    code="SKILL_VERSION_NOT_RUNTIME_READY",
                    data={"skill_id": str(skill_id), "reason": reason},
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
            try:
                highest = semver.Version.parse(highest_str)
            except ValueError as exc:
                raise InvalidRequestError(
                    "A stored skill version is not valid semver; cannot validate the new version.",
                    code="SKILL_VERSION_STORED_INVALID",
                    data={"skill_id": str(skill_id), "stored_version": highest_str},
                ) from exc
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
        *,
        limit: Optional[int] = None,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[List[JoySafeterSkillVersion], bool]:
        """Return ``(versions, has_more)`` for a skill, newest first.

        Fix #3: the route declared ``limit`` / ``after_id`` and hardcoded
        ``has_more=False`` while the service ignored both. This wires real
        cursor pagination through the repo. The repo over-fetches one row when
        ``limit`` is set; we trim it here and report whether more remain.
        """
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.READ,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )
        rows = await self.repo.list_by_skill(skill_id, limit=limit, after_id=after_id)
        if limit is not None and len(rows) > limit:
            return rows[:limit], True
        return rows, False

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
            ProjectCapability.READ,
            caller_org_role=self._caller_org_role,
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
            ProjectCapability.ADMIN,
            caller_org_role=self._caller_org_role,
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

        # If this version was serving a tier (org/public), clear that pointer
        # and recompute visibility in the SAME transaction. The FK is SET NULL,
        # but that only nulls the DB column — the in-memory skill row would keep
        # its stale pointer + stale visibility (e.g. visibility='organization'
        # with org_version_id gone). Fail-closed: drop to the highest tier still
        # backed by a live pointer (floor = project).
        if skill.org_version_id == sv.id or skill.public_version_id == sv.id:
            if skill.org_version_id == sv.id:
                skill.org_version_id = None
            if skill.public_version_id == sv.id:
                skill.public_version_id = None
            skill.visibility = recompute_visibility_from_pointers(skill)

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
            ProjectCapability.ADMIN,
            caller_org_role=self._caller_org_role,
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
        # Populate the request-scoped ``latest_version`` annotation so the
        # route response matches ``get_skill`` (which attaches it). Without
        # this, a restore returns a skill whose ``latest_version`` is the
        # ClassVar default ``None`` — inconsistent with every other skill
        # read. ``capability`` is set by the route, so we only fix this one.
        latest = await self.repo.get_latest(skill_id)
        setattr(skill, "latest_version", latest.version if latest else None)
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


from typing import Any, Dict, Literal

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


_ELIGIBILITY_NEXT_ACTIONS: dict[str | None, str] = {
    None: "none",
    "skill_not_approved": "submit_or_approve",
    "security_not_scanned": "run_security_scan",
    "security_scanning": "wait_for_scan",
    "security_failed": "fix_and_rescan",
    "security_blocked": "fix_and_rescan",
    "no_security_scan_hash": "run_security_scan",
    "content_changed_after_scan": "run_security_scan",
}


class SkillService(BaseService[JoySafeterSkill]):
    _caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER

    def __init__(
        self,
        db,
        *,
        active_org_id: Optional[str] = None,
        caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER,
    ):
        super().__init__(db)
        self.repo = SkillRepository(db)
        self.file_repo = SkillFileRepository(db)
        self.security_service = SkillSecurityService(db, active_org_id=active_org_id, caller_org_role=caller_org_role)
        # P2.9: when the API layer constructs ``SkillService`` it
        # passes ``JoySafeterAuthContext.org_id`` here. The service
        # then threads it into every ``check_skill_access`` call so the
        # capability gate respects strict org isolation. ``None`` falls
        # back to the pre-P2.9 behavior; kept for legacy callers we
        # haven't migrated yet.
        self._active_org_id = active_org_id
        # Single-axis redesign: the caller's org role, threaded into
        # every ``check_skill_access`` call so an org super-user resolves
        # to ADMIN capability on skills in their own org.
        self._caller_org_role = caller_org_role
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

    def _runtime_eligibility_next_action(self, reason: Optional[str]) -> str:
        return _ELIGIBILITY_NEXT_ACTIONS.get(reason, "review_skill")

    def _annotate_runtime_eligibility(self, skill: JoySafeterSkill) -> None:
        from app.joysafeter_shared.config import settings as app_settings

        if not app_settings.skill_security_scan_enabled:
            # When scanning is globally disabled, skip security gates for
            # runtime eligibility — only lifecycle_status matters.
            usable = skill.lifecycle_status == "approved"
            reason = None if usable else "skill_not_approved"
        else:
            from app.joysafeter_domain.services.joysafeter_skill_security import is_skill_usable
            usable, reason = is_skill_usable(skill)

        next_action = self._runtime_eligibility_next_action(reason)
        setattr(
            skill,
            "runtime_eligibility",
            {
                "usable": usable,
                "reason": reason,
                "next_action": next_action,
            },
        )

    def _agent_skill_item_refs(self, item: Any, skill_id: uuid.UUID) -> bool:
        if not isinstance(item, dict):
            return False
        value = item.get("skill_id")
        if not value:
            return False
        try:
            return uuid.UUID(str(value).removeprefix("skill_")) == skill_id
        except ValueError:
            return False

    def _agent_refs_skill(self, skills: Any, skill_id: uuid.UUID) -> bool:
        return isinstance(skills, list) and any(self._agent_skill_item_refs(item, skill_id) for item in skills)

    async def _has_skill_references(self, skill: JoySafeterSkill) -> bool:
        from sqlalchemy import select

        from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
        from app.joysafeter_domain.models.joysafeter_project import Project

        project_filter: Any
        if self._active_org_id:
            project_filter = JoySafeterAgent.project_id.in_(select(Project.id).where(Project.org_id == self._active_org_id))
        else:
            project_filter = JoySafeterAgent.project_id == skill.project_id

        result = await self.db.execute(
            select(JoySafeterAgent.id, JoySafeterAgent.skills)
            .where(project_filter, JoySafeterAgent.deleted_at.is_(None))
        )
        for row in result.all():
            if self._agent_refs_skill(row.skills, skill.id):
                return True
        return False

    async def _annotate_skill_impact(self, skill: JoySafeterSkill, *, sample_limit: int = 8) -> None:
        from sqlalchemy import select

        from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
        from app.joysafeter_domain.models.joysafeter_schedule import JoySafeterSchedule
        from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
        from app.joysafeter_domain.models.joysafeter_project import Project

        project_filter: Any
        if self._active_org_id:
            project_filter = JoySafeterAgent.project_id.in_(select(Project.id).where(Project.org_id == self._active_org_id))
        else:
            project_filter = JoySafeterAgent.project_id == skill.project_id

        agents_result = await self.db.execute(
            select(JoySafeterAgent.id, JoySafeterAgent.name, JoySafeterAgent.version, JoySafeterAgent.skills)
            .where(project_filter, JoySafeterAgent.deleted_at.is_(None))
            .limit(1000)
        )
        current_agents = [row for row in agents_result.all() if self._agent_refs_skill(row.skills, skill.id)]
        current_agent_ids = [row.id for row in current_agents]

        version_result = await self.db.execute(
            select(JoySafeterAgentVersion.id, JoySafeterAgentVersion.version, JoySafeterAgentVersion.snapshot)
            .join(JoySafeterAgent, JoySafeterAgentVersion.agent_id == JoySafeterAgent.id)
            .where(project_filter, JoySafeterAgent.deleted_at.is_(None))
            .limit(1000)
        )
        version_rows = [row for row in version_result.all() if self._agent_refs_skill(row.snapshot.get("skills"), skill.id)]

        schedule_rows = []
        task_rows = []
        if current_agent_ids:
            schedule_result = await self.db.execute(
                select(JoySafeterSchedule.id, JoySafeterSchedule.name, JoySafeterSchedule.enabled)
                .where(JoySafeterSchedule.agent_id.in_(current_agent_ids))
                .limit(1000)
            )
            schedule_rows = list(schedule_result.all())

            task_result = await self.db.execute(
                select(JoySafeterTask.id, JoySafeterTask.status)
                .where(
                    JoySafeterTask.agent_id.in_(current_agent_ids),
                    JoySafeterTask.status.notin_([status.value for status in JOYSAFETER_TERMINAL_STATUSES]),
                )
                .limit(1000)
            )
            task_rows = list(task_result.all())

        references = []
        for row in current_agents[:sample_limit]:
            references.append({"type": "agent", "id": f"agent_{row.id}", "name": row.name, "version": str(row.version)})
        remaining = max(0, sample_limit - len(references))
        for row in schedule_rows[:remaining]:
            references.append(
                {
                    "type": "schedule",
                    "id": f"schedule_{row.id}",
                    "name": row.name,
                    "status": "enabled" if row.enabled else "disabled",
                }
            )

        total = len(current_agents) + len(version_rows) + len(schedule_rows) + len(task_rows)
        setattr(
            skill,
            "impact",
            {
                "counts": {
                    "agents": len(current_agents),
                    "agent_versions": len(version_rows),
                    "schedules": len(schedule_rows),
                    "active_tasks": len(task_rows),
                    "total": total,
                },
                "references": references,
            },
        )

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
            caller_org_role=self._caller_org_role,
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
            self._annotate_runtime_eligibility(skill)
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

            # Permission check: requires READ project capability
        if current_user_id:
            await check_skill_access(
                self.db,
                skill,
                current_user_id,
                ProjectCapability.READ,
                caller_org_role=self._caller_org_role,
                active_org_id=self._active_org_id,
            )
        else:
            # Anonymous read: only the ``public`` visibility tier opens
            # the row to a missing caller. Use the same fallback as
            # ``check_skill_access``.
            effective = skill.visibility or JoySafeterSkillVisibility.PROJECT.value
            if effective != "public":
                raise AccessDeniedError(
                    "You don't have permission to access this skill",
                    code="SKILL_ACCESS_DENIED",
                )

                # Type assertion: get_with_files returns Optional[Skill], we've already checked it's not None
        skill = await self._attach_latest_version(skill)
        self._annotate_runtime_eligibility(skill)
        await self._annotate_skill_impact(skill)
        result = skill
        return result  # type: ignore

    async def create_skill(
        self,
        created_by_id: str,
        name: str,
        description: str,
        content: str,
        tags: Optional[List[str]] = None,
        source_type: str = "local",
        source_url: Optional[str] = None,
        owner_id: Optional[str] = None,
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

        # A skill is always created as a ``project`` resource. Exposure to the
        # ``organization`` / ``public`` tiers only ever happens through the
        # version-level promotion approval flow, never directly at create time.
        visibility_value = JoySafeterSkillVisibility.PROJECT.value

        skill = JoySafeterSkill(
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            source_type=source_type,
            source_url=source_url,
            owner_id=owner_id,
            created_by_id=created_by_id,
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
        owner_id: Optional[str] = None,
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

            # Permission check: requires WRITE (editor) project capability
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.WRITE,
            caller_org_role=self._caller_org_role,
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
        proposed_owner_id = skill.owner_id if owner_id is None else owner_id
        proposed_license = skill.license if license is None else license
        proposed_compatibility = skill.compatibility if compatibility is None else compatibility
        proposed_metadata = skill.meta_data
        proposed_allowed_tools = skill.allowed_tools

        # ── Ownership gate runs BEFORE any write or scan ──
        # The gate was originally placed after the security scan dispatch. That
        # meant a rejected PUT still left an audit row in
        # ``joysafeter_skill_security_scans`` claiming the spoofed
        # ``owner_id`` / ``created_by_id`` had legitimately scanned
        # the skill — useful telemetry for an attacker probing what
        # content trips which scanner rule, and noise in the
        # audit log. Running the gate first means no side effects
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
        # The ownership gate ran at the top of the function (P2.13) so we
        # don't pay any side effects of an unauthorized call. By the time
        # control reaches here, the mutation is pre-approved. Visibility is
        # NOT written here — a skill's tier is only ever changed through the
        # version-level promotion approval flow (or a takedown).
        skill.owner_id = proposed_owner_id
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
            ProjectCapability.ADMIN,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )
        _ensure_skill_mutable(skill)
        if await self._has_skill_references(skill):
            await self._annotate_skill_impact(skill)
            impact = getattr(skill, "impact", None) or {}
            raise ResourceConflictError(
                "Skill is still referenced by agents, schedules, or active tasks. Archive it or remove references before deleting.",
                code="SKILL_DELETE_HAS_REFERENCES",
                data={"skill_id": str(skill_id), "impact": impact},
                retryable=False,
                user_action="remove_references",
            )

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

            # Permission check: requires WRITE (editor) project capability
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.WRITE,
            caller_org_role=self._caller_org_role,
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

            # Permission check: requires WRITE (editor) project capability
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.WRITE,
            caller_org_role=self._caller_org_role,
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

            # Permission check: requires WRITE (editor) project capability
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.WRITE,
            caller_org_role=self._caller_org_role,
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
        from app.joysafeter_shared.config.settings import settings as _settings

        sec = self.security_service
        skill = await sec.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.WRITE,
            caller_org_role=self._caller_org_role,
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

    async def _attach_latest_version(self, skill):
        """Attach latest_version string to skill for API response."""
        ver_repo = SkillVersionRepository(self.db)
        latest = await ver_repo.get_latest(skill.id)
        skill.latest_version = latest.version if latest else None
        return skill


# ============================================================================
# skill_promotion_service.py — version-level tiered promotion approval
# ============================================================================

"""Version-level tiered promotion approval.

A skill is a project resource. Editors publish project-tier versions freely;
exposing a version to the ``organization`` or ``public`` tier goes through a
tiered, four-eyes approval:

  submit_promotion  — caller has ADMIN capability on the skill AND the target
                      version's security scan PASSED. Marks the version
                      ``pending_review`` + records ``review_target_visibility``.
  approve_promotion — caller is the org OWNER (for both org and public tiers),
                      approver != the version's submitter (four-eyes), scan
                      still passed. Sets the skill's tier pointer, raises
                      visibility, stamps the version ``approved``.
  reject_promotion  — org OWNER; version -> ``rejected``, pointer untouched.
  takedown          — org OWNER; clears a tier pointer + recomputes visibility.

The rescan auto-demote (a served version whose fresh verdict flips to
failed/blocked) lives in ``SkillSecurityService.apply_latest_scan`` so it rides
every scan-completion path.
"""


from app.joysafeter_domain.models.joysafeter_skill import (
    VISIBILITY_RANK,
    recompute_visibility_from_pointers,
)
from app.joysafeter_domain.services.joysafeter_skill_security import (
    build_scan_files,
    scan_ok,
    target_hash,
)

# Tiers a version may be promoted to. ``project`` is the no-review default
# tier and is never a promotion target; ``private`` is legacy and unreachable
# here.
_PROMOTABLE_TIERS = frozenset(
    {
        JoySafeterSkillVisibility.ORGANIZATION.value,
        JoySafeterSkillVisibility.PUBLIC.value,
    }
)


class SkillPromotionService(BaseService[JoySafeterSkill]):
    """Version-level tiered promotion approval for the single-axis model."""

    _caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER

    def __init__(
        self,
        db,
        *,
        active_org_id: Optional[str] = None,
        caller_org_role: JoySafeterRole = JoySafeterRole.MEMBER,
    ):
        super().__init__(db)
        self.skill_repo = SkillRepository(db)
        self.version_repo = SkillVersionRepository(db)
        self.version_file_repo = SkillVersionFileRepository(db)
        self._active_org_id = active_org_id
        self._caller_org_role = caller_org_role

    # ── loading helpers ─────────────────────────────────────────

    async def _get_skill_or_404(self, skill_id: uuid.UUID) -> JoySafeterSkill:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        return skill  # type: ignore[return-value,no-any-return]

    async def _get_version_or_404(self, version_id: uuid.UUID) -> JoySafeterSkillVersion:
        version = await self.version_repo.get(version_id)
        if not version:
            raise NotFoundError(
                "Skill version not found",
                code="SKILL_VERSION_NOT_FOUND",
                data={"version_id": str(version_id)},
            )
        return version  # type: ignore[return-value,no-any-return]

    def _require_org_approver(self) -> None:
        # Promotion approval / takedown is an org-superuser act (OWNER or ADMIN).
        # It was OWNER-only, but combined with four-eyes (approver != submitter)
        # that deadlocked any org whose sole owner also authored the version.
        # Widening to superuser keeps four-eyes meaningful (still needs a second
        # distinct principal) while unblocking normal 2+-admin orgs. A genuine
        # single-person org still cannot four-eyes — correct for a review gate.
        if not self._caller_org_role.is_org_superuser():
            raise AccessDeniedError(
                "Only an organization owner or admin can review skill promotions.",
                code="SKILL_PROMOTION_OWNER_ONLY",
                data={"required_org_role": [JoySafeterRole.OWNER.value, JoySafeterRole.ADMIN.value]},
            )

    async def _require_same_org(self, skill: JoySafeterSkill) -> None:
        """Reject cross-tenant promotion actions.

        ``_require_org_approver`` only proves the caller is a super-user in
        their OWN active org; it says nothing about which org the target skill
        belongs to. Without this an org-A owner/admin could approve/reject/
        takedown an org-B skill by id — a cross-tenant privilege escalation
        (exposing or pulling another tenant's content). Mirrors the org
        isolation ``check_skill_access`` applies on the ``submit`` side. A
        ``None`` active org disables the gate (legacy callers), same as there.
        """
        if self._active_org_id is None:
            return
        skill_org_id = await resolve_skill_org_id(self.db, skill)
        if skill_org_id != self._active_org_id:
            raise AccessDeniedError(
                "You don't have permission to review this skill's promotion.",
                code="SKILL_ACCESS_DENIED",
                data={"skill_id": str(skill.id), "active_org_id": self._active_org_id},
            )

    async def _require_promoted_content_scanned(self, skill: JoySafeterSkill, version: JoySafeterSkillVersion) -> None:
        """Bind the scan verdict to the exact bytes being promoted.

        ``scan_ok(skill)`` only proves the skill's CURRENT head content passed a
        clean, non-drifted scan. But a promotion exposes the frozen VERSION
        snapshot, whose content can diverge from the head (a stale version, or
        content that was published — publish only blocks HIGH/CRITICAL — but was
        never itself scanned clean). Approving/submitting such a version would
        raise the skill's cross-tier visibility (and, once the packer consumes
        the tier pointer, serve those bytes) under a scan verdict for a DIFFERENT
        payload. Require the promoted version's canonical hash to equal the hash
        the latest passed scan locked in — i.e. the exposed bytes are exactly the
        scanned bytes. Recomputed through the same ``build_scan_files`` /
        ``target_hash`` the scanner and drift gate use, over the version's frozen
        fields + its file snapshot.
        """
        version_files = await self.version_file_repo.list_by_version(version.id)
        files_payload = [
            {
                "path": vf.path,
                "file_name": vf.file_name,
                "file_type": vf.file_type,
                "content": vf.content or "",
                "storage_type": vf.storage_type,
                "storage_key": vf.storage_key,
                "size": vf.size,
            }
            for vf in version_files
        ]
        scan_files = build_scan_files(
            name=version.skill_name,
            description=version.skill_description,
            content=version.content,
            tags=list(version.tags or []),
            license=version.license,
            files=files_payload,
        )
        version_hash = target_hash(
            name=version.skill_name,
            description=version.skill_description,
            content=version.content,
            tags=list(version.tags or []),
            license=version.license,
            files=scan_files,
        )
        if version_hash != skill.security_scan_hash:
            raise ResourceConflictError(
                "This version's content does not match the skill's latest passed "
                "security scan; rescan the current content and publish it as the "
                "version you promote.",
                code="SKILL_PROMOTION_SCAN_NOT_PASSED",
                data={
                    "skill_id": str(skill.id),
                    "version_id": str(version.id),
                    "reason": "version_content_not_scanned",
                },
            )

    # ── submit ──────────────────────────────────────────────────

    async def submit_promotion(
        self,
        *,
        target_tier: str,
        current_user_id: str,
        version_id: Optional[uuid.UUID] = None,
        skill_id: Optional[uuid.UUID] = None,
    ) -> JoySafeterSkillVersion:
        """Submit a version for promotion to ``organization`` or ``public``.

        GUARD: caller holds ADMIN capability on the skill.
        PRECONDITION: the target version's security scan PASSED (``scan_ok``).
        Effect: version -> ``pending_review`` + ``review_target_visibility``.
        """
        if target_tier not in _PROMOTABLE_TIERS:
            raise InvalidRequestError(
                f"Cannot promote to tier {target_tier!r}; must be one of {sorted(_PROMOTABLE_TIERS)}.",
                code="SKILL_PROMOTION_TIER_INVALID",
                data={"target_tier": target_tier},
            )

        version = await self._resolve_target_version(version_id=version_id, skill_id=skill_id)
        skill = await self._get_skill_or_404(version.skill_id)

        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            ProjectCapability.ADMIN,
            caller_org_role=self._caller_org_role,
            active_org_id=self._active_org_id,
        )

        ok, reason = scan_ok(skill)
        if not ok:
            raise ResourceConflictError(
                "The skill's security scan has not passed; cannot submit for promotion.",
                code="SKILL_PROMOTION_SCAN_NOT_PASSED",
                data={"skill_id": str(skill.id), "version_id": str(version.id), "reason": reason},
            )
        # Bind the passed scan to the exact bytes being promoted (this version).
        await self._require_promoted_content_scanned(skill, version)

        # Idempotent when already pending for the SAME tier; conflict when
        # pending for a different tier (the caller must resolve the existing
        # review first).
        if version.lifecycle_status == "pending_review":
            if version.review_target_visibility == target_tier:
                return version
            raise ResourceConflictError(
                "This version is already pending review for a different tier.",
                code="SKILL_PROMOTION_ALREADY_PENDING",
                data={
                    "version_id": str(version.id),
                    "pending_tier": version.review_target_visibility,
                    "requested_tier": target_tier,
                },
            )

        version.lifecycle_status = "pending_review"
        version.review_target_visibility = target_tier
        await self.db.commit()
        # NOTE: do NOT ``db.refresh(version)`` here. With
        # ``expire_on_commit=False`` the mapped COLUMN values just set survive
        # the commit and stay readable. ``refresh()`` would instead expire the
        # ``lazy="selectin"`` relationships (``.skill`` / ``.published_by`` /
        # ``.approved_by``) and a later attribute access on the returned object
        # would fire a *sync* lazy load outside the async greenlet →
        # ``MissingGreenlet``. Callers that need a relationship must re-select.
        return version

    async def _resolve_target_version(
        self,
        *,
        version_id: Optional[uuid.UUID],
        skill_id: Optional[uuid.UUID],
    ) -> JoySafeterSkillVersion:
        if version_id is not None:
            return await self._get_version_or_404(version_id)
        if skill_id is not None:
            latest = await self.version_repo.get_latest(skill_id)
            if not latest:
                raise NotFoundError(
                    "Skill has no published version to promote",
                    code="SKILL_VERSION_NOT_FOUND",
                    data={"skill_id": str(skill_id)},
                )
            return latest  # type: ignore[return-value,no-any-return]
        raise InvalidRequestError(
            "submit_promotion requires either version_id or skill_id",
            code="SKILL_PROMOTION_TARGET_MISSING",
        )

    # ── approve ─────────────────────────────────────────────────

    async def approve_promotion(
        self,
        version_id: uuid.UUID,
        current_user_id: str,
    ) -> JoySafeterSkillVersion:
        """Approve a pending promotion. Org owner or admin, four-eyes enforced."""
        self._require_org_approver()
        version = await self._get_version_or_404(version_id)
        skill = await self._get_skill_or_404(version.skill_id)
        await self._require_same_org(skill)

        if version.lifecycle_status != "pending_review" or not version.review_target_visibility:
            raise ResourceConflictError(
                "This version is not pending review.",
                code="SKILL_PROMOTION_NOT_PENDING",
                data={"version_id": str(version.id), "lifecycle_status": version.lifecycle_status},
            )

        # Four-eyes: the approver must differ from the version's submitter.
        if current_user_id == version.published_by_id:
            raise AccessDeniedError(
                "The submitter cannot approve their own promotion (four-eyes).",
                code="SKILL_PROMOTION_FOUR_EYES",
                data={"version_id": str(version.id)},
            )

        # Re-check the scan still passes before exposing the content.
        ok, reason = scan_ok(skill)
        if not ok:
            raise ResourceConflictError(
                "The skill's security scan no longer passes; cannot approve promotion.",
                code="SKILL_PROMOTION_SCAN_NOT_PASSED",
                data={"skill_id": str(skill.id), "version_id": str(version.id), "reason": reason},
            )
        # Bind the passed scan to the exact bytes being exposed (this version).
        await self._require_promoted_content_scanned(skill, version)

        target_tier = version.review_target_visibility
        if target_tier == JoySafeterSkillVisibility.PUBLIC.value:
            skill.public_version_id = version.id
        elif target_tier == JoySafeterSkillVisibility.ORGANIZATION.value:
            skill.org_version_id = version.id
        else:  # pragma: no cover — submit already gates the tier vocabulary
            raise InvalidRequestError(
                f"Unsupported promotion tier {target_tier!r}",
                code="SKILL_PROMOTION_TIER_INVALID",
                data={"version_id": str(version.id), "target_tier": target_tier},
            )

        # Raise visibility to at least the approved tier (project<org<public).
        if VISIBILITY_RANK.get(skill.visibility, 0) < VISIBILITY_RANK[target_tier]:
            skill.visibility = target_tier

        version.lifecycle_status = "approved"
        version.approved_by_id = current_user_id
        version.approved_at = datetime.now(timezone.utc)
        version.review_target_visibility = None

        await self.db.commit()
        # See ``submit_promotion``: skip ``refresh`` to avoid expiring the
        # selectin relationships (columns survive under expire_on_commit=False).
        return version

    # ── reject ──────────────────────────────────────────────────

    async def reject_promotion(
        self,
        version_id: uuid.UUID,
        current_user_id: str,
        reason: Optional[str] = None,
    ) -> JoySafeterSkillVersion:
        """Reject a pending promotion. Org owner or admin. Pointer untouched."""
        self._require_org_approver()
        version = await self._get_version_or_404(version_id)
        skill = await self._get_skill_or_404(version.skill_id)
        await self._require_same_org(skill)

        if version.lifecycle_status != "pending_review":
            raise ResourceConflictError(
                "This version is not pending review.",
                code="SKILL_PROMOTION_NOT_PENDING",
                data={"version_id": str(version.id), "lifecycle_status": version.lifecycle_status},
            )

        version.lifecycle_status = "rejected"
        version.review_target_visibility = None
        await self.db.commit()
        # See ``submit_promotion``: skip ``refresh`` (selectin-relationship trap).
        return version

    # ── takedown ────────────────────────────────────────────────

    async def takedown(
        self,
        skill_id: uuid.UUID,
        tier: str,
        current_user_id: str,
    ) -> JoySafeterSkill:
        """Pull a skill down from a tier. Org owner or admin.

        Clears the tier pointer and recomputes visibility to the highest tier
        still backed by a non-null pointer (floor ``project``, fail-closed).
        """
        self._require_org_approver()
        if tier not in _PROMOTABLE_TIERS:
            raise InvalidRequestError(
                f"Cannot take down tier {tier!r}; must be one of {sorted(_PROMOTABLE_TIERS)}.",
                code="SKILL_PROMOTION_TIER_INVALID",
                data={"tier": tier},
            )
        skill = await self._get_skill_or_404(skill_id)
        await self._require_same_org(skill)

        if tier == JoySafeterSkillVisibility.PUBLIC.value:
            skill.public_version_id = None
        else:
            skill.org_version_id = None
        skill.visibility = recompute_visibility_from_pointers(skill)

        await self.db.commit()
        # See ``submit_promotion``: skip ``refresh``. ``skill`` has
        # ``lazy="selectin"`` relationships (``owner`` / ``created_by`` /
        # ``files``); refreshing would expire them and a later access would
        # trip ``MissingGreenlet``. The mutated columns survive the commit.
        return skill
