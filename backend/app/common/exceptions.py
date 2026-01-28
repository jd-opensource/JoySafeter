"""
统一异常体系（唯一入口）

- **异常类**：统一继承 `AppException(HTTPException)`，支持 `status_code`（HTTP）与 `code`（业务/错误码）分离，
  并通过 `data` 携带额外错误详情。
- **全局 handler**：提供 FastAPI 异常处理函数与一键注册函数 `register_exception_handlers`，
  确保返回 `app.common.response.error_response` 规定的统一响应格式。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError as PydanticValidationError

from app.common.response import error_response


class AppException(HTTPException):
    """应用基础异常（推荐业务代码统一抛此类或其子类）"""

    code: int
    data: Any

    def __init__(
        self,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        message: str = "Internal Server Error",
        *,
        code: int | None = None,
        data: Any = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        super().__init__(status_code=status_code, detail=message, headers=headers)
        self.code = status_code if code is None else code
        self.data = data


# 常用 HTTP 异常（业务侧可直接 raise）


class NotFoundException(AppException):
    """资源未找到（404）"""

    def __init__(self, message: str = "Resource not found", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_404_NOT_FOUND, message=message, code=code, data=data)


class BadRequestException(AppException):
    """请求错误（400）"""

    def __init__(self, message: str = "Bad request", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, message=message, code=code, data=data)


class UnauthorizedException(AppException):
    """未授权（401）"""

    def __init__(self, message: str = "Unauthorized", *, code: int | None = None, data: Any = None):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            code=code,
            data=data,
            headers={"WWW-Authenticate": "Bearer"},
        )


class ForbiddenException(AppException):
    """禁止访问（403）"""

    def __init__(self, message: str = "Forbidden", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, message=message, code=code, data=data)


class ValidationException(AppException):
    """请求参数校验失败（422）"""

    def __init__(self, message: str = "Validation error", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, message=message, code=code, data=data)


class ConflictException(AppException):
    """资源冲突（409）"""

    def __init__(self, message: str = "Resource conflict", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_409_CONFLICT, message=message, code=code, data=data)


class TooManyRequestsException(AppException):
    """请求过多（429）"""

    def __init__(self, message: str = "Too many requests", *, code: int | None = None, data: Any = None):
        super().__init__(status_code=status.HTTP_429_TOO_MANY_REQUESTS, message=message, code=code, data=data)


class InternalServerException(AppException):
    """内部错误（500）"""

    def __init__(self, message: str = "Internal Server Error", *, code: int | None = 1007, data: Any = None):
        super().__init__(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, message=message, code=code, data=data)


class ClientClosedException(AppException):
    """客户端提前断开（499）"""

    def __init__(self, message: str = "Client has closed the connection", *, code: int | None = 1008, data: Any = None):
        # 499 非标准 HTTP 状态码，但部分网关/日志体系会使用
        super().__init__(status_code=499, message=message, code=code, data=data)


class BusinessLogicException(BadRequestException):
    """业务逻辑错误（默认 400，业务码默认 1006）"""

    def __init__(self, message: str, *, code: int | None = 1006, data: Any = None):
        super().__init__(message=message, code=code, data=data)


class ParameterValidationException(BadRequestException):
    """参数/业务校验错误（默认 400，业务码默认 1001；历史兼容）"""

    def __init__(self, message: str, *, code: int | None = 1001, data: Any = None):
        super().__init__(message=message, code=code, data=data)


# 兼容别名（来自历史 app/exceptions.py 的命名）

# 旧命名语义：Authentication -> 401，Authorization -> 403
AuthenticationException = UnauthorizedException
AuthorizationException = ForbiddenException
ResourceNotFoundException = NotFoundException
ResourceConflictException = ConflictException


# 统一错误响应构造 & 全局异常 handler


def create_error_response(*, status_code: int, code: int, message: str, data: Any = None) -> Response:
    """构造统一错误响应（符合 app.common.response.error_response）。"""
    return JSONResponse(
        status_code=status_code,
        content=error_response(message=message, code=code, data=data),
    )


async def app_exception_handler(request: Request, exc: AppException) -> Response:
    """处理应用异常（AppException）。"""
    code_value = getattr(exc, "code", exc.status_code)
    code = code_value if isinstance(code_value, int) else exc.status_code
    return create_error_response(
        status_code=exc.status_code,
        code=code,
        message=str(exc.detail),
        data=getattr(exc, "data", None),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """处理 FastAPI/Starlette HTTPException（非 AppException）。"""
    return create_error_response(
        status_code=exc.status_code,
        code=exc.status_code,
        message=str(exc.detail),
        data=getattr(exc, "data", None),
    )


def _format_validation_errors(errors: Iterable[Mapping[str, Any]]) -> List[dict[str, Any]]:
    formatted: List[dict[str, Any]] = []
    for err in errors:
        loc = err.get("loc", ())
        field_path = ".".join(str(x) for x in loc)
        formatted.append(
            {
                "field": field_path,
                "message": err.get("msg"),
                "type": err.get("type"),
            }
        )
    return formatted


async def request_validation_exception_handler(request: Request, exc: Exception) -> Response:
    """处理请求校验异常（RequestValidationError / PydanticValidationError）。"""
    errors: List[dict[str, Any]] = []
    if isinstance(exc, (RequestValidationError, PydanticValidationError)):
        errors = _format_validation_errors(exc.errors())

    return create_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Request parameter validation failed",
        data={"validation_errors": errors} if errors else None,
    )


async def general_exception_handler(request: Request, exc: Exception) -> Response:
    """处理未捕获异常（500）。"""
    try:
        from loguru import logger

        logger.exception("Unhandled exception: {}", exc)
    except Exception:
        # logger 不可用时降级
        pass

    debug = False
    try:
        from app.core.settings import settings

        debug = bool(getattr(settings, "debug", False))
    except Exception:
        debug = False

    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message=str(exc) if debug else "Internal Server Error",
        data={"error_type": type(exc).__name__} if debug else None,
    )


def register_exception_handlers(app: Any) -> None:
    """
    一键注册异常处理器到 FastAPI app。

    说明：保持此函数不强依赖 FastAPI 类型，避免导入时循环依赖。
    """
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    app.add_exception_handler(PydanticValidationError, request_validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)


# 便捷 raise_*（来自历史 app/exceptions.py）


def raise_validation_error(message: str, data: Any = None) -> None:
    raise ParameterValidationException(message, code=1001, data=data)


def raise_auth_error(message: str = "Authentication failed, please sign in again", data: Any = None) -> None:
    raise UnauthorizedException(message, code=1002, data=data)


def raise_permission_error(message: str = "Insufficient permissions", data: Any = None) -> None:
    raise ForbiddenException(message, code=1003, data=data)


def raise_not_found_error(resource: str, data: Any = None) -> None:
    raise NotFoundException(f"{resource} not found", code=1004, data=data)


def raise_conflict_error(message: str, data: Any = None) -> None:
    raise ConflictException(message, code=1005, data=data)


def raise_client_closed_error(message: str = "Client has closed the connection", data: Any = None) -> None:
    raise ClientClosedException(message, code=1008, data=data)


def raise_business_error(message: str, data: Any = None) -> None:
    raise BusinessLogicException(message, code=1006, data=data)


def raise_internal_error(message: str = "Internal server error", data: Any = None) -> None:
    raise InternalServerException(message, code=1007, data=data)
