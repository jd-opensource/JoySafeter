from __future__ import annotations

import uuid
from typing import Any, Optional

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_storage_mount import (
    JoySafeterSessionStorageMount,
    JoySafeterStorageMountAudit,
    JoySafeterStorageOrganizationGrant,
    JoySafeterStorageProjectGrant,
    JoySafeterStorageVolume,
)
from app.joysafeter_domain.schemas.joysafeter_storage_mount import (
    CreateStorageVolumeRequest,
    StorageOrganizationGrantInput,
    StorageOrganizationGrantResponse,
    StorageProjectGrantInput,
    StorageProjectGrantResponse,
    StorageVolumeResponse,
    UpdateStorageVolumeRequest,
)
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.utils.datetime import utc_now


def _prefix_allows(sub_path: str, prefixes: list[str]) -> bool:
    sub_path = (sub_path or "").strip("/")
    if not prefixes:
        return sub_path == ""
    for prefix in prefixes:
        prefix = str(prefix or "").strip("/")
        if prefix == "" or sub_path == prefix or sub_path.startswith(f"{prefix}/"):
            return True
    return False


def _access_allows(requested: str, maximum: str) -> bool:
    if requested == "read_only":
        return True
    return requested == "read_write" and maximum == "read_write"


def _access_min(*accesses: str) -> str:
    return "read_only" if any(access == "read_only" for access in accesses) else "read_write"


def _quota_min(*quotas: Optional[int]) -> Optional[int]:
    values = [quota for quota in quotas if quota is not None]
    return min(values) if values else None


def _prefixes_within(child_prefixes: list[str], parent_prefixes: list[str]) -> bool:
    if not child_prefixes:
        return True
    if not parent_prefixes:
        return True
    return all(_prefix_allows(prefix, parent_prefixes) for prefix in child_prefixes)


def _intersect_prefixes(*prefix_sets: list[str]) -> list[str]:
    normalized_sets = [list(prefixes or []) for prefixes in prefix_sets]
    constrained = [prefixes for prefixes in normalized_sets if prefixes]
    if not constrained:
        return []
    candidates = constrained[-1]
    for prefixes in reversed(constrained[:-1]):
        narrowed = [prefix for prefix in candidates if _prefix_allows(prefix, prefixes)]
        widened = [prefix for prefix in prefixes if _prefix_allows(prefix, candidates)]
        candidates = list(dict.fromkeys(narrowed + widened))
    return candidates


class StorageMountService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_volumes(self, *, include_disabled: bool = False) -> list[JoySafeterStorageVolume]:
        query = select(JoySafeterStorageVolume).where(JoySafeterStorageVolume.deleted_at.is_(None))
        if not include_disabled:
            query = query.where(JoySafeterStorageVolume.enabled.is_(True))
        query = query.order_by(JoySafeterStorageVolume.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def list_volumes_for_project(
        self, project_id: Optional[str], *, include_disabled: bool = False
    ) -> list[JoySafeterStorageVolume]:
        if not project_id:
            return []
        project = await self._get_project(project_id)
        query = (
            select(JoySafeterStorageVolume)
            .join(
                JoySafeterStorageOrganizationGrant,
                and_(
                    JoySafeterStorageOrganizationGrant.volume_id == JoySafeterStorageVolume.id,
                    JoySafeterStorageOrganizationGrant.org_id == project.org_id,
                ),
            )
            .join(JoySafeterStorageProjectGrant, JoySafeterStorageProjectGrant.volume_id == JoySafeterStorageVolume.id)
            .where(
                JoySafeterStorageVolume.deleted_at.is_(None),
                JoySafeterStorageProjectGrant.project_id == project_id,
            )
        )
        if not include_disabled:
            query = query.where(
                JoySafeterStorageVolume.enabled.is_(True),
                JoySafeterStorageOrganizationGrant.enabled.is_(True),
                JoySafeterStorageProjectGrant.enabled.is_(True),
            )
        query = query.order_by(JoySafeterStorageVolume.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_volume(self, volume_id: uuid.UUID) -> Optional[JoySafeterStorageVolume]:
        result = await self.db.execute(
            select(JoySafeterStorageVolume).where(
                JoySafeterStorageVolume.id == volume_id,
                JoySafeterStorageVolume.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_project_volume(
        self, volume_id: uuid.UUID, project_id: Optional[str]
    ) -> Optional[JoySafeterStorageVolume]:
        if not project_id:
            return None
        project = await self._get_project(project_id)
        result = await self.db.execute(
            select(JoySafeterStorageVolume)
            .join(
                JoySafeterStorageOrganizationGrant,
                and_(
                    JoySafeterStorageOrganizationGrant.volume_id == JoySafeterStorageVolume.id,
                    JoySafeterStorageOrganizationGrant.org_id == project.org_id,
                ),
            )
            .join(JoySafeterStorageProjectGrant, JoySafeterStorageProjectGrant.volume_id == JoySafeterStorageVolume.id)
            .where(
                JoySafeterStorageVolume.id == volume_id,
                JoySafeterStorageVolume.deleted_at.is_(None),
                JoySafeterStorageProjectGrant.project_id == project_id,
            )
        )
        return result.scalars().unique().one_or_none()

    async def ensure_project_volume_access(self, volume_id: uuid.UUID, project_id: Optional[str]) -> None:
        if not project_id:
            raise InvalidRequestError(
                code="PROJECT_SCOPE_REQUIRED",
                message="Project scope is required for storage volume access",
                data={"volume_id": str(volume_id)},
                user_action="switch_project",
            )
        if not await self.get_project_volume(volume_id, project_id):
            raise InvalidRequestError(
                code="STORAGE_VOLUME_NOT_ALLOWED",
                message="Storage volume is not allowed for current project",
                data={"volume_id": str(volume_id)},
                user_action="fix_input",
            )

    async def get_volume_by_ref(self, volume_ref: str) -> Optional[JoySafeterStorageVolume]:
        result = await self.db.execute(
            select(JoySafeterStorageVolume).where(
                JoySafeterStorageVolume.volume_ref == volume_ref,
                JoySafeterStorageVolume.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def create_volume(
        self, req: CreateStorageVolumeRequest, *, actor_user_id: Optional[str] = None
    ) -> JoySafeterStorageVolume:
        existing = await self.get_volume_by_ref(req.volume_ref)
        if existing:
            raise ResourceConflictError(
                code="STORAGE_VOLUME_REF_EXISTS",
                message=f"Storage volume already exists: {req.volume_ref}",
                data={"volume_ref": req.volume_ref},
            )
        volume = JoySafeterStorageVolume(
            volume_ref=req.volume_ref,
            backend_type=req.backend_type,
            display_name=req.display_name,
            description=req.description,
            max_access=req.max_access,
            allowed_prefixes=req.allowed_prefixes,
            docker=req.docker,
            k8s=req.k8s,
            quota_bytes=req.quota_bytes,
            enabled=req.enabled,
            metadata_=req.metadata,
        )
        self.db.add(volume)
        await self.db.flush()
        for org_grant in req.organization_grants:
            self._validate_policy_within_volume(
                volume, org_grant.max_access, org_grant.allowed_prefixes, org_grant.quota_bytes
            )
            self.db.add(self._org_grant_model(volume.id, org_grant))
        if req.organization_grants:
            await self.db.flush()
        for project_grant in req.project_grants:
            await self._validate_project_grant(volume, project_grant)
            self.db.add(self._grant_model(volume.id, project_grant))
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume.id,
                user_id=actor_user_id,
                action="volume.create",
                volume_ref=volume.volume_ref,
                detail={"backend_type": volume.backend_type},
            )
        )
        await self.db.commit()
        await self.db.refresh(volume)
        return volume

    async def update_volume(
        self,
        volume_id: uuid.UUID,
        req: UpdateStorageVolumeRequest,
        *,
        actor_user_id: Optional[str] = None,
    ) -> JoySafeterStorageVolume:
        volume = await self.get_volume(volume_id)
        if not volume:
            raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
        fields = req.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")
        for key, value in fields.items():
            setattr(volume, key, value)
        volume.updated_at = utc_now()
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume.id,
                user_id=actor_user_id,
                action="volume.update",
                volume_ref=volume.volume_ref,
                detail={"fields": sorted(fields.keys())},
            )
        )
        await self.db.commit()
        await self.db.refresh(volume)
        return volume

    async def delete_volume(self, volume_id: uuid.UUID, *, actor_user_id: Optional[str] = None) -> bool:
        volume = await self.get_volume(volume_id)
        if not volume:
            return False
        active_mounts = await self.db.execute(
            select(JoySafeterSessionStorageMount.id)
            .where(
                JoySafeterSessionStorageMount.volume_id == volume_id,
                JoySafeterSessionStorageMount.detached_at.is_(None),
            )
            .limit(1)
        )
        if active_mounts.scalar_one_or_none():
            raise ResourceConflictError(
                code="STORAGE_VOLUME_IN_USE",
                message="Storage volume has active session mounts",
                data={"volume_id": str(volume_id)},
            )
        volume.deleted_at = utc_now()
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume.id,
                user_id=actor_user_id,
                action="volume.delete",
                volume_ref=volume.volume_ref,
            )
        )
        await self.db.commit()
        return True

    async def list_grants(self, volume_id: uuid.UUID) -> list[JoySafeterStorageProjectGrant]:
        result = await self.db.execute(
            select(JoySafeterStorageProjectGrant)
            .where(JoySafeterStorageProjectGrant.volume_id == volume_id)
            .order_by(JoySafeterStorageProjectGrant.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_organization_grants(self, volume_id: uuid.UUID) -> list[JoySafeterStorageOrganizationGrant]:
        result = await self.db.execute(
            select(JoySafeterStorageOrganizationGrant)
            .where(JoySafeterStorageOrganizationGrant.volume_id == volume_id)
            .order_by(JoySafeterStorageOrganizationGrant.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_project_grants_for_org(
        self, volume_id: uuid.UUID, org_id: str
    ) -> list[JoySafeterStorageProjectGrant]:
        result = await self.db.execute(
            select(JoySafeterStorageProjectGrant)
            .join(Project, Project.id == JoySafeterStorageProjectGrant.project_id)
            .where(
                JoySafeterStorageProjectGrant.volume_id == volume_id,
                Project.org_id == org_id,
            )
            .order_by(JoySafeterStorageProjectGrant.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_organization_volumes(
        self, org_id: str, *, include_disabled: bool = False
    ) -> list[JoySafeterStorageVolume]:
        query = (
            select(JoySafeterStorageVolume)
            .join(
                JoySafeterStorageOrganizationGrant,
                JoySafeterStorageOrganizationGrant.volume_id == JoySafeterStorageVolume.id,
            )
            .where(
                JoySafeterStorageVolume.deleted_at.is_(None),
                JoySafeterStorageOrganizationGrant.org_id == org_id,
            )
        )
        if not include_disabled:
            query = query.where(
                JoySafeterStorageVolume.enabled.is_(True),
                JoySafeterStorageOrganizationGrant.enabled.is_(True),
            )
        query = query.order_by(JoySafeterStorageVolume.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().unique().all())

    async def get_organization_volume(self, volume_id: uuid.UUID, org_id: str) -> Optional[JoySafeterStorageVolume]:
        result = await self.db.execute(
            select(JoySafeterStorageVolume)
            .join(
                JoySafeterStorageOrganizationGrant,
                JoySafeterStorageOrganizationGrant.volume_id == JoySafeterStorageVolume.id,
            )
            .where(
                JoySafeterStorageVolume.id == volume_id,
                JoySafeterStorageVolume.deleted_at.is_(None),
                JoySafeterStorageOrganizationGrant.org_id == org_id,
            )
        )
        return result.scalars().unique().one_or_none()

    async def get_organization_grant(
        self, volume_id: uuid.UUID, org_id: str
    ) -> Optional[JoySafeterStorageOrganizationGrant]:
        result = await self.db.execute(
            select(JoySafeterStorageOrganizationGrant).where(
                JoySafeterStorageOrganizationGrant.volume_id == volume_id,
                JoySafeterStorageOrganizationGrant.org_id == org_id,
            )
        )
        return result.scalar_one_or_none()

    async def replace_organization_grant(
        self,
        volume_id: uuid.UUID,
        grant: StorageOrganizationGrantInput,
        *,
        actor_user_id: Optional[str] = None,
    ) -> JoySafeterStorageOrganizationGrant:
        volume = await self.get_volume(volume_id)
        if not volume:
            raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
        self._validate_policy_within_volume(volume, grant.max_access, grant.allowed_prefixes, grant.quota_bytes)
        existing = await self.get_organization_grant(volume_id, grant.org_id)
        if existing:
            existing.max_access = grant.max_access
            existing.allowed_prefixes = grant.allowed_prefixes
            existing.quota_bytes = grant.quota_bytes
            existing.enabled = grant.enabled
            existing.updated_at = utc_now()
            row = existing
        else:
            row = self._org_grant_model(volume_id, grant)
            self.db.add(row)
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume_id,
                user_id=actor_user_id,
                action="org_grant.upsert",
                volume_ref=volume.volume_ref,
                detail={"org_id": grant.org_id, "max_access": grant.max_access, "enabled": grant.enabled},
            )
        )
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete_organization_grant(
        self, volume_id: uuid.UUID, org_id: str, *, actor_user_id: Optional[str] = None
    ) -> bool:
        volume = await self.get_volume(volume_id)
        if not volume:
            raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
        grant = await self.get_organization_grant(volume_id, org_id)
        if not grant:
            return False
        await self.db.execute(
            delete(JoySafeterStorageProjectGrant).where(
                JoySafeterStorageProjectGrant.volume_id == volume_id,
                JoySafeterStorageProjectGrant.project_id.in_(select(Project.id).where(Project.org_id == org_id)),
            )
        )
        await self.db.delete(grant)
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume_id,
                user_id=actor_user_id,
                action="org_grant.delete",
                volume_ref=volume.volume_ref,
                detail={"org_id": org_id, "project_grants_deleted": True},
            )
        )
        await self.db.commit()
        return True

    async def replace_grant(
        self,
        volume_id: uuid.UUID,
        grant: StorageProjectGrantInput,
        *,
        actor_user_id: Optional[str] = None,
        org_id_scope: Optional[str] = None,
    ) -> JoySafeterStorageProjectGrant:
        volume = await self.get_volume(volume_id)
        if not volume:
            raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
        await self._validate_project_grant(volume, grant, org_id_scope=org_id_scope)
        existing_result = await self.db.execute(
            select(JoySafeterStorageProjectGrant).where(
                JoySafeterStorageProjectGrant.volume_id == volume_id,
                JoySafeterStorageProjectGrant.project_id == grant.project_id,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing:
            existing.max_access = grant.max_access
            existing.allowed_prefixes = grant.allowed_prefixes
            existing.quota_bytes = grant.quota_bytes
            existing.enabled = grant.enabled
            existing.updated_at = utc_now()
            row = existing
        else:
            row = self._grant_model(volume_id, grant)
            self.db.add(row)
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume_id,
                project_id=grant.project_id,
                user_id=actor_user_id,
                action="grant.upsert",
                volume_ref=volume.volume_ref,
                detail={"max_access": grant.max_access, "enabled": grant.enabled},
            )
        )
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def delete_grant(
        self,
        volume_id: uuid.UUID,
        project_id: str,
        *,
        actor_user_id: Optional[str] = None,
        org_id_scope: Optional[str] = None,
    ) -> bool:
        volume = await self.get_volume(volume_id)
        if not volume:
            raise NotFoundError(code="STORAGE_VOLUME_NOT_FOUND", message="Storage volume not found")
        if org_id_scope is not None:
            project = await self._get_project(project_id)
            if project.org_id != org_id_scope:
                raise InvalidRequestError(
                    code="PROJECT_SCOPE_REQUIRED",
                    message="Project must belong to current organization",
                    data={"project_id": project_id},
                    user_action="switch_project",
                )
        result = await self.db.execute(
            select(JoySafeterStorageProjectGrant).where(
                JoySafeterStorageProjectGrant.volume_id == volume_id,
                JoySafeterStorageProjectGrant.project_id == project_id,
            )
        )
        grant = result.scalar_one_or_none()
        if not grant:
            return False
        await self.db.delete(grant)
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume_id,
                project_id=project_id,
                user_id=actor_user_id,
                action="grant.delete",
                volume_ref=volume.volume_ref,
            )
        )
        await self.db.commit()
        return True

    async def catalog_for_project(self, project_id: Optional[str]) -> list[dict[str, Any]]:
        if not project_id:
            return []
        volumes = await self._authorized_volumes(project_id)
        return [self._catalog_item(volume, org_grant, grant) for volume, org_grant, grant in volumes]

    async def validate_mount_resources(self, resources: list[Any], project_id: Optional[str]) -> None:
        if not resources:
            return
        if not project_id:
            raise InvalidRequestError(
                code="PROJECT_SCOPE_REQUIRED",
                message="Project scope is required for storage mounts",
                user_action="switch_project",
            )
        authorized = {
            volume.volume_ref: (volume, org_grant, grant)
            for volume, org_grant, grant in await self._authorized_volumes(project_id)
        }
        for resource in resources:
            if getattr(resource, "type", "storage") != "storage":
                continue
            entry = authorized.get(resource.volume_ref)
            if not entry:
                raise InvalidRequestError(
                    code="STORAGE_VOLUME_NOT_ALLOWED",
                    message=f"Storage volume is not allowed: {resource.volume_ref}",
                    data={"volume_ref": resource.volume_ref},
                    user_action="fix_input",
                )
            volume, org_grant, grant = entry
            effective_access = self._effective_access(volume, org_grant, grant)
            if not _access_allows(resource.access or "read_only", effective_access):
                raise InvalidRequestError(
                    code="STORAGE_ACCESS_DENIED",
                    message=f"Storage volume does not allow {resource.access} access: {resource.volume_ref}",
                    data={"volume_ref": resource.volume_ref, "max_access": effective_access},
                    user_action="fix_input",
                )
            prefixes = self._effective_prefixes(volume, org_grant, grant)
            if not _prefix_allows(resource.sub_path or "", prefixes):
                raise InvalidRequestError(
                    code="STORAGE_SUB_PATH_DENIED",
                    message="sub_path is outside allowed prefixes",
                    data={"volume_ref": resource.volume_ref, "sub_path": resource.sub_path},
                    user_action="fix_input",
                )

    async def record_audit(
        self,
        *,
        action: str,
        volume_ref: Optional[str] = None,
        volume_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
        session_id: Optional[uuid.UUID] = None,
        environment_id: Optional[uuid.UUID] = None,
        user_id: Optional[str] = None,
        mount_path: Optional[str] = None,
        sub_path: Optional[str] = None,
        access: Optional[str] = None,
        result: str = "success",
        detail: Optional[dict[str, Any]] = None,
        commit: bool = True,
    ) -> None:
        self.db.add(
            JoySafeterStorageMountAudit(
                volume_id=volume_id,
                project_id=project_id,
                session_id=session_id,
                environment_id=environment_id,
                user_id=user_id,
                action=action,
                volume_ref=volume_ref,
                mount_path=mount_path,
                sub_path=sub_path,
                access=access,
                result=result,
                detail=detail or {},
            )
        )
        if commit:
            await self.db.commit()

    async def list_audit(
        self,
        *,
        project_id: Optional[str] = None,
        org_id: Optional[str] = None,
        volume_id: Optional[uuid.UUID] = None,
        limit: int = 100,
    ) -> list[JoySafeterStorageMountAudit]:
        conditions = []
        if project_id is not None:
            conditions.append(JoySafeterStorageMountAudit.project_id == project_id)
        if org_id is not None:
            # Scope to all projects belonging to this organization.
            conditions.append(
                JoySafeterStorageMountAudit.project_id.in_(select(Project.id).where(Project.org_id == org_id))
            )
        if volume_id is not None:
            conditions.append(JoySafeterStorageMountAudit.volume_id == volume_id)
        query = select(JoySafeterStorageMountAudit)
        if conditions:
            query = query.where(and_(*conditions))
        query = query.order_by(JoySafeterStorageMountAudit.created_at.desc()).limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    def _grant_model(self, volume_id: uuid.UUID, grant: StorageProjectGrantInput) -> JoySafeterStorageProjectGrant:
        return JoySafeterStorageProjectGrant(
            volume_id=volume_id,
            project_id=grant.project_id,
            max_access=grant.max_access,
            allowed_prefixes=grant.allowed_prefixes,
            quota_bytes=grant.quota_bytes,
            enabled=grant.enabled,
        )

    def _org_grant_model(
        self, volume_id: uuid.UUID, grant: StorageOrganizationGrantInput
    ) -> JoySafeterStorageOrganizationGrant:
        return JoySafeterStorageOrganizationGrant(
            volume_id=volume_id,
            org_id=grant.org_id,
            max_access=grant.max_access,
            allowed_prefixes=grant.allowed_prefixes,
            quota_bytes=grant.quota_bytes,
            enabled=grant.enabled,
        )

    async def _get_project(self, project_id: str) -> Project:
        result = await self.db.execute(select(Project).where(Project.id == project_id, Project.archived_at.is_(None)))
        project = result.scalar_one_or_none()
        if not project:
            raise InvalidRequestError(
                code="PROJECT_NOT_FOUND",
                message="Project not found",
                data={"project_id": project_id},
                user_action="fix_input",
            )
        return project

    def _validate_policy_within_volume(
        self,
        volume: JoySafeterStorageVolume,
        max_access: str,
        allowed_prefixes: list[str],
        quota_bytes: Optional[int],
    ) -> None:
        if not _access_allows(max_access, volume.max_access):
            raise InvalidRequestError(
                code="STORAGE_ACCESS_DENIED",
                message="Grant access exceeds volume maximum access",
                data={"volume_ref": volume.volume_ref, "max_access": volume.max_access},
                user_action="fix_input",
            )
        if not _prefixes_within(allowed_prefixes, list(volume.allowed_prefixes or [])):
            raise InvalidRequestError(
                code="STORAGE_PREFIX_DENIED",
                message="Grant allowed_prefixes exceed volume allowed prefixes",
                data={"volume_ref": volume.volume_ref},
                user_action="fix_input",
            )
        if volume.quota_bytes is not None and quota_bytes is not None and quota_bytes > volume.quota_bytes:
            raise InvalidRequestError(
                code="STORAGE_QUOTA_DENIED",
                message="Grant quota exceeds volume quota",
                data={"volume_ref": volume.volume_ref, "quota_bytes": volume.quota_bytes},
                user_action="fix_input",
            )

    async def _validate_project_grant(
        self,
        volume: JoySafeterStorageVolume,
        grant: StorageProjectGrantInput,
        *,
        org_id_scope: Optional[str] = None,
    ) -> None:
        project = await self._get_project(grant.project_id)
        if org_id_scope is not None and project.org_id != org_id_scope:
            raise InvalidRequestError(
                code="PROJECT_SCOPE_REQUIRED",
                message="Project must belong to current organization",
                data={"project_id": grant.project_id},
                user_action="switch_project",
            )
        org_grant = await self.get_organization_grant(volume.id, project.org_id)
        if not org_grant or not org_grant.enabled:
            raise InvalidRequestError(
                code="STORAGE_ORG_GRANT_REQUIRED",
                message="Storage volume must be granted to the organization before granting it to a project",
                data={"volume_ref": volume.volume_ref, "org_id": project.org_id},
                user_action="fix_input",
            )
        effective_org_access = _access_min(volume.max_access, org_grant.max_access)
        if not _access_allows(grant.max_access, effective_org_access):
            raise InvalidRequestError(
                code="STORAGE_ACCESS_DENIED",
                message="Project grant access exceeds organization grant access",
                data={"volume_ref": volume.volume_ref, "max_access": effective_org_access},
                user_action="fix_input",
            )
        effective_org_prefixes = _intersect_prefixes(
            list(volume.allowed_prefixes or []), list(org_grant.allowed_prefixes or [])
        )
        if not _prefixes_within(grant.allowed_prefixes, effective_org_prefixes):
            raise InvalidRequestError(
                code="STORAGE_PREFIX_DENIED",
                message="Project grant allowed_prefixes exceed organization grant prefixes",
                data={"volume_ref": volume.volume_ref, "org_id": project.org_id},
                user_action="fix_input",
            )
        effective_org_quota = _quota_min(volume.quota_bytes, org_grant.quota_bytes)
        if (
            effective_org_quota is not None
            and grant.quota_bytes is not None
            and grant.quota_bytes > effective_org_quota
        ):
            raise InvalidRequestError(
                code="STORAGE_QUOTA_DENIED",
                message="Project grant quota exceeds organization grant quota",
                data={"volume_ref": volume.volume_ref, "quota_bytes": effective_org_quota},
                user_action="fix_input",
            )

    async def _authorized_volumes(
        self,
        project_id: Optional[str],
    ) -> list[
        tuple[
            JoySafeterStorageVolume,
            Optional[JoySafeterStorageOrganizationGrant],
            Optional[JoySafeterStorageProjectGrant],
        ]
    ]:
        if project_id is None:
            result = await self.db.execute(
                select(JoySafeterStorageVolume).where(
                    JoySafeterStorageVolume.deleted_at.is_(None),
                    JoySafeterStorageVolume.enabled.is_(True),
                )
            )
            return [(volume, None, None) for volume in result.scalars().all()]
        project = await self._get_project(project_id)
        result = await self.db.execute(
            select(JoySafeterStorageVolume, JoySafeterStorageOrganizationGrant, JoySafeterStorageProjectGrant)
            .join(
                JoySafeterStorageOrganizationGrant,
                and_(
                    JoySafeterStorageOrganizationGrant.volume_id == JoySafeterStorageVolume.id,
                    JoySafeterStorageOrganizationGrant.org_id == project.org_id,
                ),
            )
            .join(JoySafeterStorageProjectGrant, JoySafeterStorageProjectGrant.volume_id == JoySafeterStorageVolume.id)
            .where(
                JoySafeterStorageVolume.deleted_at.is_(None),
                JoySafeterStorageVolume.enabled.is_(True),
                JoySafeterStorageOrganizationGrant.enabled.is_(True),
                JoySafeterStorageProjectGrant.project_id == project_id,
                JoySafeterStorageProjectGrant.enabled.is_(True),
            )
            .order_by(JoySafeterStorageVolume.display_name.asc())
        )
        return [(volume, org_grant, grant) for volume, org_grant, grant in result.all()]

    def _effective_access(
        self,
        volume: JoySafeterStorageVolume,
        org_grant: Optional[JoySafeterStorageOrganizationGrant],
        grant: Optional[JoySafeterStorageProjectGrant],
    ) -> str:
        return _access_min(
            volume.max_access,
            org_grant.max_access if org_grant else "read_write",
            grant.max_access if grant else "read_write",
        )

    def _effective_prefixes(
        self,
        volume: JoySafeterStorageVolume,
        org_grant: Optional[JoySafeterStorageOrganizationGrant],
        grant: Optional[JoySafeterStorageProjectGrant],
    ) -> list[str]:
        return _intersect_prefixes(
            list(volume.allowed_prefixes or []),
            list(org_grant.allowed_prefixes or []) if org_grant else [],
            list(grant.allowed_prefixes or []) if grant else [],
        )

    def _effective_quota(
        self,
        volume: JoySafeterStorageVolume,
        org_grant: Optional[JoySafeterStorageOrganizationGrant],
        grant: Optional[JoySafeterStorageProjectGrant],
    ) -> Optional[int]:
        return _quota_min(
            volume.quota_bytes, org_grant.quota_bytes if org_grant else None, grant.quota_bytes if grant else None
        )

    def _catalog_item(
        self,
        volume: JoySafeterStorageVolume,
        org_grant: Optional[JoySafeterStorageOrganizationGrant],
        grant: Optional[JoySafeterStorageProjectGrant],
    ) -> dict[str, Any]:
        return {
            "volume_ref": volume.volume_ref,
            "backend_type": volume.backend_type,
            "display_name": volume.display_name,
            "description": volume.description,
            "max_access": self._effective_access(volume, org_grant, grant),
            "allowed_prefixes": self._effective_prefixes(volume, org_grant, grant),
            "quota_bytes": self._effective_quota(volume, org_grant, grant),
            "used_bytes": volume.used_bytes,
            "supports_docker": bool((volume.docker or {}).get("host_path")),
            "supports_k8s": bool((volume.k8s or {}).get("pvc")),
        }


def volume_to_response(
    volume: JoySafeterStorageVolume,
    grants: list[JoySafeterStorageProjectGrant] | None = None,
    organization_grants: list[JoySafeterStorageOrganizationGrant] | None = None,
    *,
    include_runtime_specs: bool = True,
) -> StorageVolumeResponse:
    return StorageVolumeResponse(
        id=volume.id,
        volume_ref=volume.volume_ref,
        backend_type=volume.backend_type,
        display_name=volume.display_name,
        description=volume.description,
        max_access=volume.max_access,
        allowed_prefixes=volume.allowed_prefixes or [],
        docker=(volume.docker or {}) if include_runtime_specs else {},
        k8s=(volume.k8s or {}) if include_runtime_specs else {},
        quota_bytes=volume.quota_bytes,
        used_bytes=volume.used_bytes,
        enabled=volume.enabled,
        metadata=volume.metadata_ or {},
        grants=[StorageProjectGrantResponse.model_validate(g) for g in grants or []],
        organization_grants=[StorageOrganizationGrantResponse.model_validate(g) for g in organization_grants or []],
        created_at=volume.created_at,
        updated_at=volume.updated_at,
    )
