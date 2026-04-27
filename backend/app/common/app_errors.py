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

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)
        self.data = _normalize_data(self.data)

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "data": dict(self.data) if self.data is not None else None,
        }


class DomainError(AppError):
    pass


class InfraError(AppError):
    pass


class AuthError(AppError):
    pass


class ValidationError(AppError):
    pass


class PermissionDeniedError(AppError):
    pass


class ConflictError(AppError):
    pass


class RateLimitError(AppError):
    pass


class InternalError(AppError):
    pass


class NotFoundError(DomainError):
    def __init__(self, message: str = "资源不存在", *, code: str = "NOT_FOUND", data: Mapping[str, Any] | None = None):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class InvalidRequestError(DomainError):
    def __init__(self, message: str = "请求错误", *, code: str = "BAD_REQUEST", data: Mapping[str, Any] | None = None):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class AuthenticationError(AuthError):
    def __init__(self, message: str = "未认证", *, code: str = "UNAUTHORIZED", data: Mapping[str, Any] | None = None):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class AccessDeniedError(PermissionDeniedError):
    def __init__(self, message: str = "无权限", *, code: str = "FORBIDDEN", data: Mapping[str, Any] | None = None):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class ResourceConflictError(ConflictError):
    def __init__(self, message: str = "资源冲突", *, code: str = "CONFLICT", data: Mapping[str, Any] | None = None):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class RateLimitExceededError(RateLimitError):
    def __init__(
        self,
        message: str = "请求过于频繁",
        *,
        code: str = "RATE_LIMITED",
        data: Mapping[str, Any] | None = None,
    ):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class InternalServiceError(InternalError):
    def __init__(
        self, message: str = "内部错误", *, code: str = "INTERNAL_ERROR", data: Mapping[str, Any] | None = None
    ):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class ServiceUnavailableError(InfraError):
    def __init__(
        self,
        message: str = "服务暂不可用",
        *,
        code: str = "SERVICE_UNAVAILABLE",
        data: Mapping[str, Any] | None = None,
    ):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class ClientClosedError(AppError):
    def __init__(
        self, message: str = "客户端已关闭连接", *, code: str = "CLIENT_CLOSED", data: Mapping[str, Any] | None = None
    ):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class RequestValidationAppError(ValidationError):
    def __init__(
        self,
        message: str = "请求参数校验失败",
        *,
        code: str = "REQUEST_VALIDATION_ERROR",
        data: Mapping[str, Any] | None = None,
    ):
        super().__init__(code=code, message=message, data=_normalize_data(data))


class ModelConfigError(DomainError):
    MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
    MODEL_NO_CREDENTIALS = "MODEL_NO_CREDENTIALS"
    PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"
    MODEL_NAME_REQUIRED = "MODEL_NAME_REQUIRED"
    BUILD_COPILOT_MODEL_REQUIRED = "BUILD_COPILOT_MODEL_REQUIRED"

    def __init__(self, code: str, message: str = "模型配置错误", *, params: Mapping[str, Any] | None = None):
        super().__init__(code=code, message=message, data=_normalize_data(params))
