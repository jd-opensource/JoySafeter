"""Skill Version Service — publish, list, get, delete, restore."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

import semver

from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.common.skill_permissions import check_skill_access
from app.joysafeter_domain.models.skill import Skill, SkillFile
from app.joysafeter_domain.models.skill_collaborator import CollaboratorRole
from app.joysafeter_domain.models.skill_version import SkillVersion, SkillVersionFile
from app.joysafeter_domain.repositories.skill import SkillFileRepository, SkillRepository
from app.joysafeter_domain.repositories.skill_version import SkillVersionFileRepository, SkillVersionRepository

from .base import BaseService


class SkillVersionService(BaseService[SkillVersion]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = SkillVersionRepository(db)
        self.file_repo = SkillVersionFileRepository(db)
        self.skill_repo = SkillRepository(db)
        self.skill_file_repo = SkillFileRepository(db)

    async def publish_version(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        version_str: str,
        release_notes: Optional[str] = None,
        is_superuser: bool = False,
    ) -> SkillVersion:
        skill = await self._get_skill_with_files_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.publisher,
            is_superuser=is_superuser,
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
        sv = SkillVersion(
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
            vf = SkillVersionFile(
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
    ) -> List[SkillVersion]:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.viewer,
            is_superuser=is_superuser,
        )
        return await self.repo.list_by_skill(skill_id)  # type: ignore[return-value,no-any-return]

    async def get_version(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> SkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.viewer,
            is_superuser=is_superuser,
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
    ) -> SkillVersion:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.viewer,
            is_superuser=is_superuser,
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
            CollaboratorRole.admin,
            is_superuser=is_superuser,
        )
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

    async def _find_version_referrers(
        self, skill_id: uuid.UUID, version_str: str
    ) -> list[dict]:
        """Find agents (live draft + persisted agent_versions) that reference
        ``(skill_id, version_str)`` in their ``skills`` array. Returns a list
        of compact descriptors usable in the error payload."""
        from sqlalchemy import text as sa_text
        import json

        from app.joysafeter_domain.models.agent import (
            JoySafeterAgent,
            JoySafeterAgentVersion,
        )

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
            stmt = sa_text(
                "SELECT id, name FROM joysafeter_agents "
                "WHERE skills @> CAST(:needle AS jsonb)"
            ).bindparams(needle=needle)
            result = await self.db.execute(stmt)
            for row in result.mappings():
                referrers.append({
                    "kind": "agent",
                    "agent_id": str(row["id"]),
                    "name": row["name"],
                })

        # 2) Frozen agent_version snapshots
        for needle in candidates:
            stmt = sa_text(
                "SELECT agent_id, version FROM joysafeter_agent_versions "
                "WHERE (snapshot->'skills') @> CAST(:needle AS jsonb)"
            ).bindparams(needle=needle)
            result = await self.db.execute(stmt)
            for row in result.mappings():
                referrers.append({
                    "kind": "agent_version",
                    "agent_id": str(row["agent_id"]),
                    "agent_version": row["version"],
                })

        return referrers

    async def restore_draft(
        self,
        skill_id: uuid.UUID,
        version_str: str,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> Skill:
        skill = await self._get_skill_with_files_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.publisher,
            is_superuser=is_superuser,
        )
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
            sf = SkillFile(
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

    async def _get_skill_or_404(self, skill_id: uuid.UUID) -> Skill:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        return skill  # type: ignore[return-value,no-any-return]

    async def _get_skill_with_files_or_404(self, skill_id: uuid.UUID) -> Skill:
        skill = await self.skill_repo.get_with_files(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        return skill  # type: ignore[return-value,no-any-return]
