"""File service - handles upload, download, list, delete operations."""

import hashlib
import mimetypes
import os
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid_utils import uuid7

from app.joysafeter_domain.models.joysafeter_file import JoySafeterFile
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.storage.base import StorageBackend

MAX_FILENAME_LENGTH = 255

ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".txt", ".csv", ".md", ".html", ".xml", ".json", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".c", ".cpp", ".h",
    ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh", ".sql",
    ".css", ".vue", ".svelte",
    ".jpeg", ".jpg", ".png", ".gif", ".webp",
    ".zip", ".tar", ".gz", ".7z", ".rar",
    ".apk",
}


def _sanitize_filename(name: str) -> str:
    # Strip directory components — only keep the filename
    name = os.path.basename(name.replace("\\", "/"))
    name = re.sub(r'[<>:"|?*\x00-\x1f\x7f]', "_", name)
    name = name.strip(". ")
    if len(name) > MAX_FILENAME_LENGTH:
        ext = ""
        if "." in name:
            ext = name[name.rfind("."):]
        name = name[: MAX_FILENAME_LENGTH - len(ext)] + ext
    return name or "unnamed"


def _validate_extension(filename: str) -> None:
    ext = ""
    if "." in filename:
        ext = filename[filename.rfind("."):].lower()
    if ext and ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"File type {ext} is not supported")


def _make_storage_key(file_id: uuid.UUID, filename: str) -> str:
    shard = str(file_id)[:2]
    safe = _sanitize_filename(filename)
    return f"files/{shard}/{file_id}_{safe}"


class FileService:
    def __init__(self, storage: StorageBackend):
        self._storage = storage

    async def upload(
        self,
        db: AsyncSession,
        project_id: str,
        filename: str,
        data: bytes,
        content_type: str | None = None,
    ) -> JoySafeterFile:
        if len(data) == 0:
            raise ValueError("File cannot be empty")
        max_file_size = settings.max_upload_file_bytes
        if len(data) > max_file_size:
            raise ValueError(f"File size exceeds maximum ({max_file_size // 1024 // 1024}MB)")

        safe_name = _sanitize_filename(filename)
        _validate_extension(safe_name)

        # Validate content_type — never trust client-supplied MIME type for dangerous types
        if not content_type:
            content_type = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"
        else:
            _DANGEROUS_CONTENT_TYPES = {"text/html", "application/javascript", "text/javascript", "application/x-httpd-php"}
            if content_type.lower() in _DANGEROUS_CONTENT_TYPES:
                content_type = "application/octet-stream"

        file_id = uuid7()
        sha = hashlib.sha256(data).hexdigest()
        storage_key = _make_storage_key(file_id, safe_name)

        await self._storage.put(storage_key, data, content_type)

        record = JoySafeterFile(
            id=file_id,
            project_id=project_id,
            filename=safe_name,
            purpose="user_upload",
            content_type=content_type,
            size_bytes=len(data),
            sha256=sha,
            storage_key=storage_key,
            downloadable=False,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)
        return record

    async def get_metadata(
        self, db: AsyncSession, file_id: uuid.UUID, project_id: str
    ) -> JoySafeterFile | None:
        result = await db.execute(
            select(JoySafeterFile).where(
                JoySafeterFile.id == file_id,
                JoySafeterFile.project_id == project_id,
                JoySafeterFile.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def list_files(
        self,
        db: AsyncSession,
        project_id: str,
        limit: int = 20,
        after_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ) -> tuple[list[JoySafeterFile], bool]:
        q = (
            select(JoySafeterFile)
            .where(
                JoySafeterFile.project_id == project_id,
                JoySafeterFile.deleted_at.is_(None),
            )
            .order_by(desc(JoySafeterFile.created_at))
        )
        if session_id:
            q = q.where(JoySafeterFile.session_id == session_id)
        if after_id:
            q = q.where(JoySafeterFile.id < after_id)
        q = q.limit(limit + 1)

        result = await db.execute(q)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        return rows, has_more

    async def download(
        self, db: AsyncSession, file_id: uuid.UUID, project_id: str
    ) -> tuple[bytes, JoySafeterFile]:
        record = await self.get_metadata(db, file_id, project_id)
        if not record:
            raise FileNotFoundError("File not found")

        data = await self._storage.get(record.storage_key)
        return data, record

    async def get_presign_url(
        self, db: AsyncSession, file_id: uuid.UUID, project_id: str
    ) -> tuple[str | None, JoySafeterFile]:
        record = await self.get_metadata(db, file_id, project_id)
        if not record:
            raise FileNotFoundError("File not found")

        url = await self._storage.presign_url(record.storage_key)
        return url, record

    async def delete(
        self, db: AsyncSession, file_id: uuid.UUID, project_id: str
    ) -> bool:
        record = await self.get_metadata(db, file_id, project_id)
        if not record:
            return False

        record.deleted_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            await self._storage.delete(record.storage_key)
        except Exception:
            pass
        return True
