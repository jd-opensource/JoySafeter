"""Schemas for Files API."""

import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str = "file"
    filename: str
    purpose: str
    content_type: str
    size_bytes: int
    sha256: str
    downloadable: bool
    session_id: Optional[str] = None
    created_at: datetime

    @classmethod
    def from_model(cls, obj) -> "FileResponse":
        return cls(
            id=f"file_{obj.id}",
            filename=obj.filename,
            purpose=obj.purpose,
            content_type=obj.content_type,
            size_bytes=obj.size_bytes,
            sha256=obj.sha256,
            downloadable=obj.downloadable,
            session_id=f"sesn_{obj.session_id}" if obj.session_id else None,
            created_at=obj.created_at,
        )


class FileDeleteResponse(BaseModel):
    id: str
    deleted: bool = True
