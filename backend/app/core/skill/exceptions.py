"""Custom exceptions for skill operations.

All skill exceptions inherit from AppError subclasses, integrating with
the unified error system while remaining catchable by specific type.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.common.app_errors import (
    AccessDeniedError,
    DomainError,
    InternalServiceError,
    NotFoundError,
)


class SkillLoadError(DomainError):
    _default_source: str = "runtime"

    def __init__(
        self,
        message: str = "技能加载失败",
        *,
        code: str = "SKILL_LOAD_FAILED",
        data: Mapping[str, Any] | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(code=code, message=message, data=data, **kw)


class SkillNotFoundError(NotFoundError):
    def __init__(
        self,
        message: str = "技能未找到",
        *,
        code: str = "SKILL_NOT_FOUND",
        data: Mapping[str, Any] | None = None,
        **kw: Any,
    ):
        super().__init__(code=code, message=message, data=data, **kw)


class SkillPermissionDeniedError(AccessDeniedError):
    def __init__(
        self,
        message: str = "技能访问被拒绝",
        *,
        code: str = "SKILL_ACCESS_DENIED",
        data: Mapping[str, Any] | None = None,
        **kw: Any,
    ):
        super().__init__(code=code, message=message, data=data, **kw)


class SkillFileWriteError(InternalServiceError):
    _default_source: str = "runtime"

    def __init__(
        self,
        message: str = "技能文件写入失败",
        *,
        code: str = "SKILL_FILE_WRITE_FAILED",
        data: Mapping[str, Any] | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(code=code, message=message, data=data, **kw)
