"""
工作空间文件存储服务
"""

from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import UploadFile
from jose import JWTError, jwt

from app.common.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.core.settings import settings
from app.models.access_control import PermissionType
from app.models.auth import AuthUser as User
from app.models.workspace import WorkspaceMemberRole
from app.repositories.workspace import WorkspaceMemberRepository, WorkspaceRepository
from app.repositories.workspace_file import WorkspaceStoredFileRepository
from app.utils.path_utils import sanitize_filename

from .base import BaseService


class WorkspaceFileService(BaseService):
    """工作空间文件业务逻辑"""

    CONTEXT = WorkspaceStoredFileRepository.CONTEXT_WORKSPACE
    MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100MB 单文件限制
    DEFAULT_STORAGE_LIMIT_BYTES = 5 * 1024 * 1024 * 1024  # 5GB 简单配额（可按需调整/接入计费）
    DOWNLOAD_TOKEN_EXPIRE_MINUTES = 15

    def __init__(self, db):
        super().__init__(db)
        self.workspace_repo = WorkspaceRepository(db)
        self.member_repo = WorkspaceMemberRepository(db)
        self.file_repo = WorkspaceStoredFileRepository(db)

    # ------------------------------------------------------------------ #
    # 内部工具
    # ------------------------------------------------------------------ #
    def _storage_root(self) -> Path:
        """统一的文件根目录"""
        return Path(settings.WORKSPACE_ROOT) / "workspace_files"

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，避免路径穿越

        使用统一的 sanitize_filename 工具函数。
        """
        return sanitize_filename(filename or "unnamed")

    def _generate_key(self, workspace_id: uuid.UUID, filename: str) -> str:
        """生成存储 Key：workspace/<workspace_id>/<timestamp>-<random>-<safe_name>"""
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        random_part = secrets.token_hex(4)
        safe_name = self._sanitize_filename(filename).replace(" ", "-")
        return f"workspace/{workspace_id}/{timestamp}-{random_part}-{safe_name}"

    def _build_serve_path(self, workspace_id: uuid.UUID, file_id: uuid.UUID) -> str:
        """生成文件对外访问路径（未附带签名）"""
        return f"/api/workspaces/{workspace_id}/files/{file_id}/serve"

    async def _write_file(self, path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    def _get_permission_by_role(self, role: WorkspaceMemberRole | None) -> PermissionType:
        if role in (WorkspaceMemberRole.owner, WorkspaceMemberRole.admin, WorkspaceMemberRole.member):
            return PermissionType.write
        return PermissionType.read

    def _check_permission(self, required: PermissionType, actual: PermissionType) -> None:
        if required == PermissionType.read:
            return
        if required == PermissionType.write and actual != PermissionType.write:
            raise ForbiddenException("Write permission required")

    async def _ensure_member_role(self, workspace_id: uuid.UUID, user: User) -> WorkspaceMemberRole:
        workspace = await self.workspace_repo.get(workspace_id)
        if not workspace:
            raise NotFoundException("Workspace not found")

        if user.is_superuser or workspace.owner_id == user.id:
            return WorkspaceMemberRole.owner

        member = await self.member_repo.get_member(workspace_id, user.id)
        if not member:
            raise ForbiddenException("No access to workspace")
        return member.role  # type: ignore

    def _token_payload(self, workspace_id: uuid.UUID, file_id: uuid.UUID, user_id: uuid.UUID) -> Dict:
        now = datetime.now(timezone.utc)
        return {
            "sub": str(user_id),
            "workspace_id": str(workspace_id),
            "file_id": str(file_id),
            "type": "workspace_file",
            "iat": now,
            "exp": now + timedelta(minutes=self.DOWNLOAD_TOKEN_EXPIRE_MINUTES),
        }

    def _validate_download_token(self, token: str, workspace_id: uuid.UUID, file_id: uuid.UUID) -> Optional[str]:
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=[settings.algorithm],
                options={"verify_aud": False},
            )
            if payload.get("type") != "workspace_file":
                return None
            if payload.get("workspace_id") != str(workspace_id):
                return None
            if payload.get("file_id") != str(file_id):
                return None
            sub = payload.get("sub")
            return str(sub) if sub is not None else None
        except JWTError:
            return None

    def _file_path_from_key(self, key: str) -> Path:
        return self._storage_root() / key

    def get_file_path(self, record) -> Path:
        """获取文件绝对路径"""
        return self._file_path_from_key(record.key)

    def _serialize_file(self, record) -> Dict:
        serve_path = self._build_serve_path(record.workspace_id, record.id)
        return {
            "id": str(record.id),
            "workspaceId": str(record.workspace_id) if record.workspace_id else None,
            "name": record.original_name,
            "key": record.key,
            "path": serve_path,
            "url": serve_path,
            "size": record.size,
            "type": record.content_type,
            "uploadedBy": str(record.user_id),
            "uploadedAt": record.uploaded_at,
        }

    # ------------------------------------------------------------------ #
    # 公开方法
    # ------------------------------------------------------------------ #
    async def list_files(self, workspace_id: uuid.UUID, current_user: User) -> List[Dict]:
        role = await self._ensure_member_role(workspace_id, current_user)
        self._check_permission(PermissionType.read, self._get_permission_by_role(role))

        records = await self.file_repo.list_workspace_files(workspace_id)
        return [self._serialize_file(rec) for rec in records]

    async def upload_file(self, workspace_id: uuid.UUID, file: UploadFile, current_user: User) -> Dict:
        role = await self._ensure_member_role(workspace_id, current_user)
        self._check_permission(PermissionType.write, self._get_permission_by_role(role))

        content = await file.read()
        size = len(content)
        if size == 0:
            raise BadRequestException("File is empty")
        if size > self.MAX_FILE_SIZE_BYTES:
            raise BadRequestException("File exceeds size limit (100MB)")

        original_name = self._sanitize_filename(file.filename or "unnamed")
        exists = await self.file_repo.find_by_name(workspace_id, original_name)
        if exists:
            # 对齐旧项目：重复文件返回 409，并标记 isDuplicate
            raise ConflictException(
                f'A file named "{original_name}" already exists in this workspace',
                data={"isDuplicate": True},
            )

        # 简单配额校验
        current_usage = await self.file_repo.sum_user_usage(current_user.id)
        if current_usage + size > self.DEFAULT_STORAGE_LIMIT_BYTES:
            raise ForbiddenException("Storage limit exceeded")

        key = self._generate_key(workspace_id, original_name)
        path = self._file_path_from_key(key)

        await self._write_file(path, content)

        record = await self.file_repo.create(
            {
                "key": key,
                "user_id": current_user.id,
                "workspace_id": workspace_id,
                "context": self.CONTEXT,
                "original_name": original_name,
                "content_type": file.content_type or "application/octet-stream",
                "size": size,
            }
        )
        await self.commit()

        return self._serialize_file(record)

    async def delete_file(self, workspace_id: uuid.UUID, file_id: uuid.UUID, current_user: User) -> None:
        role = await self._ensure_member_role(workspace_id, current_user)
        self._check_permission(PermissionType.write, self._get_permission_by_role(role))

        record = await self.file_repo.get_by_id_and_workspace(file_id, workspace_id)
        if not record:
            raise NotFoundException("File not found")

        file_path = self._file_path_from_key(record.key)
        if file_path.exists():
            await asyncio.to_thread(file_path.unlink)

        await self.file_repo.delete(record.id)
        await self.commit()

    async def generate_download_url(self, workspace_id: uuid.UUID, file_id: uuid.UUID, current_user: User) -> str:
        role = await self._ensure_member_role(workspace_id, current_user)
        self._check_permission(PermissionType.read, self._get_permission_by_role(role))

        record = await self.file_repo.get_by_id_and_workspace(file_id, workspace_id)
        if not record:
            raise NotFoundException("File not found")

        import uuid as uuid_lib

        file_uuid = uuid_lib.UUID(file_id) if isinstance(file_id, str) else file_id
        user_uuid = uuid_lib.UUID(current_user.id) if isinstance(current_user.id, str) else current_user.id
        token = jwt.encode(
            self._token_payload(workspace_id, file_uuid, user_uuid),
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        return f"{self._build_serve_path(workspace_id, file_id)}?token={token}"

    async def get_file_record(self, workspace_id: uuid.UUID, file_id: uuid.UUID):
        record = await self.file_repo.get_by_id_and_workspace(file_id, workspace_id)
        if not record:
            raise NotFoundException("File not found")
        return record

    async def read_file_bytes(self, record) -> bytes:
        file_path = self._file_path_from_key(record.key)
        if not file_path.exists():
            raise NotFoundException("File content missing")
        return await asyncio.to_thread(file_path.read_bytes)

    async def validate_token_or_user(
        self,
        workspace_id: uuid.UUID,
        file_id: uuid.UUID,
        token: Optional[str],
        current_user: Optional[User],
    ) -> None:
        if token:
            user_sub = self._validate_download_token(token, workspace_id, file_id)
            if not user_sub:
                raise ForbiddenException("Invalid or expired download token")
            return

        if not current_user:
            raise ForbiddenException("Authentication required")
        role = await self._ensure_member_role(workspace_id, current_user)
        self._check_permission(PermissionType.read, self._get_permission_by_role(role))

    async def get_user_storage_usage(self, user: User) -> Dict:
        used = await self.file_repo.sum_user_usage(user.id)
        limit_bytes = self.DEFAULT_STORAGE_LIMIT_BYTES
        percent_used = (used / limit_bytes * 100) if limit_bytes else 0
        return {
            "usedBytes": used,
            "limitBytes": limit_bytes,
            "percentUsed": percent_used,
        }
