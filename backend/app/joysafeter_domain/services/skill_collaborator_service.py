"""Skill Collaborator Service — add/update/remove collaborators + ownership transfer."""

from __future__ import annotations

import uuid
from typing import List

from app.joysafeter_shared.common.app_errors import AccessDeniedError, InvalidRequestError, NotFoundError
from app.joysafeter_shared.common.skill_permissions import check_skill_access
from app.joysafeter_domain.models.skill import Skill
from app.joysafeter_domain.models.skill_collaborator import CollaboratorRole, SkillCollaborator
from app.joysafeter_domain.repositories.skill import SkillRepository
from app.joysafeter_domain.repositories.skill_collaborator import SkillCollaboratorRepository

from .base import BaseService


class SkillCollaboratorService(BaseService[SkillCollaborator]):
    def __init__(self, db):
        super().__init__(db)
        self.repo = SkillCollaboratorRepository(db)
        self.skill_repo = SkillRepository(db)

    async def list_collaborators(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        is_superuser: bool = False,
    ) -> tuple[List[SkillCollaborator], Skill]:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.viewer,
            is_superuser=is_superuser,
        )
        collaborators = await self.repo.list_by_skill(skill_id)
        return collaborators, skill  # type: ignore[return-value]

    async def add_collaborator(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        target_user_id: str,
        role: CollaboratorRole,
        is_superuser: bool = False,
    ) -> SkillCollaborator:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.admin,
            is_superuser=is_superuser,
        )

        if target_user_id == skill.owner_id:
            raise InvalidRequestError(
                "Cannot add the owner as a collaborator", code="SKILL_OWNER_COLLABORATOR_FORBIDDEN"
            )

        existing = await self.repo.get_by_skill_and_user(skill_id, target_user_id)
        if existing:
            raise InvalidRequestError(
                "User is already a collaborator",
                code="SKILL_COLLABORATOR_ALREADY_EXISTS",
                data={"user_id": target_user_id},
            )

        collab = SkillCollaborator(
            skill_id=skill_id,
            user_id=target_user_id,
            role=role,
            invited_by=current_user_id,
        )
        self.db.add(collab)
        await self.db.commit()
        await self.db.refresh(collab)
        return collab

    async def update_collaborator_role(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        target_user_id: str,
        new_role: CollaboratorRole,
        is_superuser: bool = False,
    ) -> SkillCollaborator:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.admin,
            is_superuser=is_superuser,
        )

        collab = await self.repo.get_by_skill_and_user(skill_id, target_user_id)
        if not collab:
            raise NotFoundError(
                "Collaborator not found",
                code="SKILL_COLLABORATOR_NOT_FOUND",
                data={"user_id": target_user_id},
            )

        collab.role = new_role
        await self.db.commit()
        await self.db.refresh(collab)
        return collab  # type: ignore[return-value,no-any-return]

    async def remove_collaborator(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        target_user_id: str,
        is_superuser: bool = False,
    ) -> None:
        skill = await self._get_skill_or_404(skill_id)
        await check_skill_access(
            self.db,
            skill,
            current_user_id,
            CollaboratorRole.admin,
            is_superuser=is_superuser,
        )

        deleted = await self.repo.delete_by_skill_and_user(skill_id, target_user_id)
        if not deleted:
            raise NotFoundError(
                "Collaborator not found",
                code="SKILL_COLLABORATOR_NOT_FOUND",
                data={"user_id": target_user_id},
            )
        await self.db.commit()

    async def transfer_ownership(
        self,
        skill_id: uuid.UUID,
        current_user_id: str,
        new_owner_id: str,
    ) -> Skill:
        """Transfer ownership. Only the current owner can do this."""
        skill = await self._get_skill_or_404(skill_id)

        if skill.owner_id != current_user_id:
            raise AccessDeniedError("Only the owner can transfer ownership", code="SKILL_OWNER_TRANSFER_FORBIDDEN")

        # Check new owner doesn't have a skill with the same name
        existing = await self.skill_repo.get_by_name_and_owner(skill.name, new_owner_id)
        if existing:
            raise InvalidRequestError(
                f"New owner already has a skill named '{skill.name}'",
                code="SKILL_NAME_ALREADY_EXISTS",
                data={"name": skill.name, "owner_id": new_owner_id},
            )

        # Remove new owner from collaborators if present
        await self.repo.delete_by_skill_and_user(skill_id, new_owner_id)

        # Remove old owner from collaborators if present (avoid UniqueConstraint violation)
        await self.repo.delete_by_skill_and_user(skill_id, current_user_id)

        # Add old owner as admin collaborator
        old_owner_collab = SkillCollaborator(
            skill_id=skill_id,
            user_id=current_user_id,
            role=CollaboratorRole.admin,
            invited_by=current_user_id,
        )
        self.db.add(old_owner_collab)

        # Transfer
        skill.owner_id = new_owner_id
        await self.db.commit()
        await self.db.refresh(skill)
        return skill

    async def _get_skill_or_404(self, skill_id: uuid.UUID) -> Skill:
        skill = await self.skill_repo.get(skill_id)
        if not skill:
            raise NotFoundError("Skill not found", code="SKILL_NOT_FOUND", data={"skill_id": str(skill_id)})
        return skill  # type: ignore[return-value,no-any-return]
