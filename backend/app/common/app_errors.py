from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _normalize_data(data: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if data is None:
        return None
    return dict(data)


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    data: dict[str, Any] | None = None
    source: str = "internal"
    retryable: bool = False
    user_action: str | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        self.data = _normalize_data(self.data)

    def to_payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "data": dict(self.data) if self.data is not None else None,
            "source": self.source,
            "retryable": self.retryable,
        }
        if self.user_action is not None:
            result["user_action"] = self.user_action
        if self.detail is not None:
            result["detail"] = self.detail
        return result


class DomainError(AppError):
    _default_source: str = "api"


class InfraError(AppError):
    _default_source: str = "runtime"


class AuthError(AppError):
    _default_source: str = "auth"


class ValidationError(AppError):
    _default_source: str = "validation"


class PermissionDeniedError(AppError):
    _default_source: str = "permission"


class ConflictError(AppError):
    _default_source: str = "api"


class RateLimitError(AppError):
    _default_source: str = "api"


class InternalError(AppError):
    _default_source: str = "internal"


class NotFoundError(DomainError):
    def __init__(
        self,
        message: str = "资源不存在",
        *,
        code: str = "NOT_FOUND",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = None,
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class InvalidRequestError(DomainError):
    def __init__(
        self,
        message: str = "请求错误",
        *,
        code: str = "BAD_REQUEST",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = None,
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class AuthenticationError(AuthError):
    def __init__(
        self,
        message: str = "未认证",
        *,
        code: str = "UNAUTHORIZED",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = "relogin",
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class AccessDeniedError(PermissionDeniedError):
    def __init__(
        self,
        message: str = "无权限",
        *,
        code: str = "FORBIDDEN",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = None,
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class ResourceConflictError(ConflictError):
    def __init__(
        self,
        message: str = "资源冲突",
        *,
        code: str = "CONFLICT",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = None,
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class RateLimitExceededError(RateLimitError):
    def __init__(
        self,
        message: str = "请求过于频繁",
        *,
        code: str = "RATE_LIMITED",
        data: Mapping[str, Any] | None = None,
        retryable: bool = True,
        user_action: str | None = "retry",
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class InternalServiceError(InternalError):
    def __init__(
        self,
        message: str = "内部错误",
        *,
        code: str = "INTERNAL_ERROR",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = None,
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class ServiceUnavailableError(InfraError):
    def __init__(
        self,
        message: str = "服务暂不可用",
        *,
        code: str = "SERVICE_UNAVAILABLE",
        data: Mapping[str, Any] | None = None,
        retryable: bool = True,
        user_action: str | None = "retry",
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class ClientClosedError(AppError):
    _default_source: str = "api"

    def __init__(
        self,
        message: str = "客户端已关闭连接",
        *,
        code: str = "CLIENT_CLOSED",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = None,
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class RequestValidationAppError(ValidationError):
    def __init__(
        self,
        message: str = "请求参数校验失败",
        *,
        code: str = "REQUEST_VALIDATION_ERROR",
        data: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = "fix_input",
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=data, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


class ModelConfigError(DomainError):
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_NO_CREDENTIALS = "MODEL_NO_CREDENTIALS"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    MODEL_NAME_REQUIRED = "MODEL_NAME_REQUIRED"
    BUILD_COPILOT_MODEL_REQUIRED = "BUILD_COPILOT_MODEL_REQUIRED"

    def __init__(
        self,
        code: str,
        message: str = "模型配置错误",
        *,
        params: Mapping[str, Any] | None = None,
        retryable: bool = False,
        user_action: str | None = "configure_model",
        detail: str | None = None,
        **kw: Any,
    ):
        kw.setdefault("source", self._default_source)
        super().__init__(
            code=code, message=message, data=params, retryable=retryable, user_action=user_action, detail=detail, **kw
        )


def normalize_app_error(
    exc: Exception,
    *,
    default_code: str = "INTERNAL_ERROR",
    default_message: str = "内部错误",
    default_data: Mapping[str, Any] | None = None,
    source: str = "internal",
    retryable: bool = False,
) -> AppError:
    if isinstance(exc, AppError):
        return exc
    return InternalServiceError(
        default_message,
        code=default_code,
        source=source,
        retryable=retryable,
        data={
            **(dict(default_data) if default_data is not None else {}),
            "detail": str(exc),
        }
        if str(exc)
        else (dict(default_data) if default_data is not None else None),
    )
