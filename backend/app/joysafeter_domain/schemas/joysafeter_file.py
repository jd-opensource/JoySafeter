"""Schemas for Files API."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.joysafeter_shared.ids import FileId, SessionId


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: FileId
    type: str = "file"
    filename: str
    purpose: str
    content_type: str
    size_bytes: int
    sha256: str
    downloadable: bool
    session_id: Optional[SessionId] = None
    created_at: datetime

    @classmethod
    def from_model(cls, obj) -> "FileResponse":
        return cls(
            id=obj.id,
            filename=obj.filename,
            purpose=obj.purpose,
            content_type=obj.content_type,
            size_bytes=obj.size_bytes,
            sha256=obj.sha256,
            downloadable=obj.downloadable,
            session_id=obj.session_id,
            created_at=obj.created_at,
        )


class FileDeleteResponse(BaseModel):
    id: FileId
    deleted: bool = True
