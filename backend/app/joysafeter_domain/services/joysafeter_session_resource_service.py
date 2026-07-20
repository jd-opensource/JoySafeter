from __future__ import annotations

import posixpath
import re
import uuid
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_session_file import JoySafeterSessionFile
from app.joysafeter_domain.models.joysafeter_session_repo import JoySafeterSessionRepo
from app.joysafeter_domain.schemas.joysafeter_session import (
    MAX_FILE_RESOURCES,
    MAX_REPO_RESOURCES,
    SessionFileResourceRequest,
    SessionFileResourceResponse,
    SessionRepoResourceRequest,
    SessionRepoResourceResponse,
)
from app.joysafeter_domain.services.joysafeter_file_service import FileService
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.storage import get_storage

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class PreparedSessionFileResource:
    file_id: uuid.UUID
    mount_path: str


@dataclass(frozen=True)
class PreparedSessionRepoResource:
    url: str
    branch: str
    mount_path: str
    mount_name: str
    encrypted_token: str


def _validate_mount_path(path: str) -> str:
    normalized = posixpath.normpath(path)
    if not normalized.startswith("/workspace/"):
        raise InvalidRequestError(
            code="SESSION_RESOURCE_MOUNT_PATH_INVALID",
            message="mount_path must be under /workspace/",
            data={"mount_path": path},
            user_action="fix_input",
        )
    if ".." in normalized.split("/"):
        raise InvalidRequestError(
            code="SESSION_RESOURCE_MOUNT_PATH_INVALID",
            message="mount_path must not contain '..' components",
            data={"mount_path": path},
            user_action="fix_input",
        )
    return normalized


def _slugify_mount_name(name: str) -> str:
    return _NON_ALNUM_RE.sub("-", name.lower()).strip("-")


class SessionResourceService:
    """Owns session file/repository resource lifecycle and storage contracts."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._file_svc = FileService(get_storage())
        self._secret_svc = SecretService(db)
        self._session_svc = SessionService(db)

    async def get_project_session_or_raise(
        self,
        session_id: uuid.UUID,
        project_id: Optional[str],
    ) -> JoySafeterSession:
        session = await self._session_svc.get_session(session_id, project_id=project_id)
        if not session or session.project_id != project_id:
            raise NotFoundError(
                code="SESSION_NOT_FOUND",
                message="Session not found",
                data={"session_id": str(session_id)},
                user_action="refresh",
            )
        return session

    @staticmethod
    def ensure_mutable(session: JoySafeterSession, session_id: uuid.UUID) -> None:
        if session.archived_at:
            raise ResourceConflictError(
                code="SESSION_ARCHIVED",
                message="Session is archived",
                data={"session_id": str(session_id)},
                user_action="refresh",
            )
        if session.status == "terminated":
            raise ResourceConflictError(
                code="SESSION_TERMINATED",
                message="Session is terminated",
                data={"session_id": str(session_id), "session_status": session.status},
                user_action="refresh",
            )
        if session.status == "rescheduling":
            raise ResourceConflictError(
                code="SESSION_RESCHEDULING",
                message="Session is rescheduling, try again later",
                data={"session_id": str(session_id), "session_status": session.status},
                retryable=True,
                user_action="retry",
            )
        if session.status != "idle":
            raise ResourceConflictError(
                code="SESSION_ALREADY_RUNNING",
                message="Session resources can only be changed while the session is idle",
                data={"session_id": str(session_id), "session_status": session.status},
                retryable=True,
                user_action="retry",
            )

    async def prepare_file_resources(
        self,
        resources: list[SessionFileResourceRequest],
        *,
        project_id: Optional[str],
        session_id: uuid.UUID | None = None,
    ) -> list[PreparedSessionFileResource]:
        if len(resources) > MAX_FILE_RESOURCES:
            raise InvalidRequestError(
                code="SESSION_FILE_RESOURCE_LIMIT_EXCEEDED",
                message=f"Too many file resources (max {MAX_FILE_RESOURCES})",
                data={"max": MAX_FILE_RESOURCES, "actual": len(resources)},
                user_action="fix_input",
            )

        prepared: list[PreparedSessionFileResource] = []
        for resource in resources:
            fid = self._parse_file_id(resource.file_id, session_id=session_id)
            record = await self._file_svc.get_metadata(self.db, fid, project_id)
            if not record:
                data: dict[str, object] = {"file_id": resource.file_id}
                if session_id is not None:
                    data["session_id"] = str(session_id)
                raise NotFoundError(
                    code="SESSION_FILE_NOT_FOUND",
                    message=f"File not found: {resource.file_id}",
                    data=data,
                    user_action="refresh",
                )
            mount_path = _validate_mount_path(resource.mount_path or f"/workspace/{record.filename}")
            prepared.append(PreparedSessionFileResource(file_id=record.id, mount_path=mount_path))
        return prepared

    async def prepare_repo_resources(
        self,
        resources: list[SessionRepoResourceRequest],
        *,
        session_id: uuid.UUID | None = None,
        existing_count: int = 0,
    ) -> list[PreparedSessionRepoResource]:
        if existing_count + len(resources) > MAX_REPO_RESOURCES:
            data: dict[str, object] = {"max": MAX_REPO_RESOURCES, "actual": existing_count + len(resources)}
            if session_id is not None:
                data["session_id"] = str(session_id)
            raise InvalidRequestError(
                code="SESSION_REPO_RESOURCE_LIMIT_EXCEEDED",
                message=f"Too many repo resources (max {MAX_REPO_RESOURCES})",
                data=data,
                user_action="fix_input",
            )

        prepared: list[PreparedSessionRepoResource] = []
        for resource in resources:
            url = (resource.url or "").strip()
            if not url:
                data = {"resource_type": "github_repository"}
                if session_id is not None:
                    data["session_id"] = str(session_id)
                raise InvalidRequestError(
                    code="SESSION_REPO_URL_REQUIRED",
                    message="Repo url is required" if session_id is not None else "repo resource url is required",
                    data=data,
                    user_action="fix_input",
                )
            mount_path = _validate_mount_path(resource.mount_path) if resource.mount_path else ""
            mount_name = resource.mount_name or _slugify_mount_name(
                url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
            )
            encrypted_token = ""
            if resource.authorization_token:
                encrypted_token = self._secret_svc.encrypt_data_for_storage({"token": resource.authorization_token})[
                    "token"
                ]
            prepared.append(
                PreparedSessionRepoResource(
                    url=url,
                    branch=resource.branch or "",
                    mount_path=mount_path,
                    mount_name=mount_name,
                    encrypted_token=encrypted_token,
                )
            )
        return prepared

    async def attach_prepared_resources(
        self,
        session_id: uuid.UUID,
        *,
        files: list[PreparedSessionFileResource],
        repos: list[PreparedSessionRepoResource],
    ) -> None:
        for resource in files:
            self.db.add(
                JoySafeterSessionFile(
                    session_id=session_id,
                    file_id=resource.file_id,
                    mount_path=resource.mount_path,
                    access="read_only",
                )
            )
        for repo in repos:
            self.db.add(
                JoySafeterSessionRepo(
                    session_id=session_id,
                    url=repo.url,
                    branch=repo.branch,
                    mount_path=repo.mount_path,
                    mount_name=repo.mount_name,
                    encrypted_token=repo.encrypted_token,
                )
            )
        if files or repos:
            await self.db.commit()

    def _session_project_exists_condition(self, session_id: uuid.UUID, project_id: Optional[str]):
        if project_id is None:
            return None
        return (
            select(JoySafeterSession.id)
            .where(
                JoySafeterSession.id == session_id,
                JoySafeterSession.project_id == project_id,
            )
            .exists()
        )

    async def list_file_records(
        self,
        session_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> list[JoySafeterSessionFile]:
        conditions = [JoySafeterSessionFile.session_id == session_id]
        project_condition = self._session_project_exists_condition(session_id, project_id)
        if project_condition is not None:
            conditions.append(project_condition)
        result = await self.db.execute(
            select(JoySafeterSessionFile).where(*conditions).order_by(JoySafeterSessionFile.created_at)
        )
        return list(result.scalars().all())

    async def list_repo_records(
        self,
        session_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> list[JoySafeterSessionRepo]:
        conditions = [JoySafeterSessionRepo.session_id == session_id]
        project_condition = self._session_project_exists_condition(session_id, project_id)
        if project_condition is not None:
            conditions.append(project_condition)
        result = await self.db.execute(
            select(JoySafeterSessionRepo).where(*conditions).order_by(JoySafeterSessionRepo.created_at)
        )
        return list(result.scalars().all())

    async def list_resource_payloads(self, session_id: uuid.UUID, project_id: Optional[str] = None) -> list[dict]:
        files = [
            SessionFileResourceResponse.model_validate(row).model_dump(mode="json")
            for row in await self.list_file_records(session_id, project_id=project_id)
        ]
        repos = [
            SessionRepoResourceResponse.model_validate(row).model_dump(mode="json")
            for row in await self.list_repo_records(session_id, project_id=project_id)
        ]
        return [*files, *repos]

    async def add_file_resource(
        self,
        session_id: uuid.UUID,
        req: SessionFileResourceRequest,
        *,
        project_id: Optional[str],
    ) -> SessionFileResourceResponse:
        await self.get_project_session_or_raise(session_id, project_id)
        prepared = await self.prepare_file_resources([req], project_id=project_id, session_id=session_id)
        resource = prepared[0]
        row = JoySafeterSessionFile(
            session_id=session_id,
            file_id=resource.file_id,
            mount_path=resource.mount_path,
            access="read_only",
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return SessionFileResourceResponse.model_validate(row)

    async def add_repo_resource(
        self,
        session_id: uuid.UUID,
        req: SessionRepoResourceRequest,
        *,
        project_id: Optional[str] = None,
    ) -> SessionRepoResourceResponse:
        await self.get_project_session_or_raise(session_id, project_id)
        existing = await self.list_repo_records(session_id, project_id=project_id)
        prepared = await self.prepare_repo_resources([req], session_id=session_id, existing_count=len(existing))
        resource = prepared[0]
        row = JoySafeterSessionRepo(
            session_id=session_id,
            url=resource.url,
            branch=resource.branch,
            mount_path=resource.mount_path,
            mount_name=resource.mount_name,
            encrypted_token=resource.encrypted_token,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return SessionRepoResourceResponse.model_validate(row)

    async def delete_resource(
        self,
        session_id: uuid.UUID,
        resource_id: str,
        project_id: Optional[str] = None,
    ) -> dict:
        rid = self._parse_resource_id(resource_id, session_id=session_id)
        row = await self._get_file_or_repo(session_id, rid, project_id=project_id)
        if row is None:
            raise NotFoundError(
                code="SESSION_RESOURCE_NOT_FOUND",
                message="Resource not found",
                data={"session_id": str(session_id), "resource_id": resource_id},
                user_action="refresh",
            )
        await self.db.delete(row)
        await self.db.commit()
        return {"id": resource_id, "deleted": True}

    async def rotate_repo_token(
        self,
        session_id: uuid.UUID,
        resource_id: str,
        authorization_token: str,
        *,
        project_id: Optional[str] = None,
    ) -> SessionRepoResourceResponse:
        rid = self._parse_resource_id(resource_id, session_id=session_id)
        conditions = [
            JoySafeterSessionRepo.id == rid,
            JoySafeterSessionRepo.session_id == session_id,
        ]
        project_condition = self._session_project_exists_condition(session_id, project_id)
        if project_condition is not None:
            conditions.append(project_condition)
        result = await self.db.execute(select(JoySafeterSessionRepo).where(*conditions))
        row = result.scalar_one_or_none()
        if not row:
            raise NotFoundError(
                code="SESSION_REPO_RESOURCE_NOT_FOUND",
                message="Repo resource not found",
                data={"session_id": str(session_id), "resource_id": resource_id},
                user_action="refresh",
            )
        row.encrypted_token = (
            self._secret_svc.encrypt_data_for_storage({"token": authorization_token})["token"]
            if authorization_token
            else ""
        )
        await self.db.commit()
        await self.db.refresh(row)
        return SessionRepoResourceResponse.model_validate(row)

    async def _get_file_or_repo(
        self,
        session_id: uuid.UUID,
        resource_id: uuid.UUID,
        project_id: Optional[str] = None,
    ) -> JoySafeterSessionFile | JoySafeterSessionRepo | None:
        project_condition = self._session_project_exists_condition(session_id, project_id)
        file_conditions = [
            JoySafeterSessionFile.id == resource_id,
            JoySafeterSessionFile.session_id == session_id,
        ]
        repo_conditions = [
            JoySafeterSessionRepo.id == resource_id,
            JoySafeterSessionRepo.session_id == session_id,
        ]
        if project_condition is not None:
            file_conditions.append(project_condition)
            repo_conditions.append(project_condition)
        file_result = await self.db.execute(select(JoySafeterSessionFile).where(*file_conditions))
        file_row = file_result.scalar_one_or_none()
        if file_row:
            return file_row
        repo_result = await self.db.execute(select(JoySafeterSessionRepo).where(*repo_conditions))
        return repo_result.scalar_one_or_none()

    @staticmethod
    def _parse_file_id(raw: str, *, session_id: uuid.UUID | None = None) -> uuid.UUID:
        s = raw.removeprefix("file_")
        try:
            return uuid.UUID(s)
        except ValueError:
            data: dict[str, object] = {"file_id": raw}
            if session_id is not None:
                data["session_id"] = str(session_id)
            raise InvalidRequestError(
                code="SESSION_FILE_ID_INVALID",
                message=f"Invalid file_id: {raw}",
                data=data,
                user_action="fix_input",
            )

    @staticmethod
    def _parse_resource_id(raw: str, *, session_id: uuid.UUID) -> uuid.UUID:
        s = raw.removeprefix("sesrsc_")
        try:
            return uuid.UUID(s)
        except ValueError:
            raise InvalidRequestError(
                code="SESSION_RESOURCE_ID_INVALID",
                message="Invalid resource_id",
                data={"session_id": str(session_id), "resource_id": raw},
                user_action="fix_input",
            )
