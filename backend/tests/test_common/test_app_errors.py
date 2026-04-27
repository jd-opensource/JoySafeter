from app.common.app_errors import (
    AppError,
    AuthError,
    ConflictError,
    DomainError,
    InfraError,
    InternalError,
    PermissionDeniedError,
    RateLimitError,
    ValidationError,
)


def test_app_error_serializes_to_canonical_payload() -> None:
    err = AppError(
        code="USER_NOT_FOUND",
        message="用户不存在",
        data={"user_id": "u-1"},
    )

    assert err.to_payload() == {
        "code": "USER_NOT_FOUND",
        "message": "用户不存在",
        "data": {"user_id": "u-1"},
    }


def test_domain_error_is_an_app_error() -> None:
    err = DomainError(
        code="NODE_MODEL_NOT_CONFIGURED",
        message="节点未配置模型",
        data={"node_id": "node-1"},
    )

    assert isinstance(err, AppError)
    assert err.to_payload() == {
        "code": "NODE_MODEL_NOT_CONFIGURED",
        "message": "节点未配置模型",
        "data": {"node_id": "node-1"},
    }


def test_validation_error_keeps_structured_data() -> None:
    err = ValidationError(
        code="REQUEST_INVALID",
        message="请求参数校验失败",
        data={"field": "workspace_id"},
    )

    assert err.to_payload()["data"] == {"field": "workspace_id"}


def test_error_families_share_canonical_app_error_shape() -> None:
    cases = [
        AuthError(code="AUTH_REQUIRED", message="请先登录"),
        ConflictError(code="AGENT_CONFLICT", message="资源冲突"),
        InfraError(code="MODEL_PROVIDER_UNAVAILABLE", message="模型服务不可用"),
        InternalError(code="INTERNAL_ERROR", message="内部错误"),
        PermissionDeniedError(code="WORKSPACE_FORBIDDEN", message="没有权限"),
        RateLimitError(code="RATE_LIMITED", message="请求过于频繁"),
    ]

    for err in cases:
        assert isinstance(err, AppError)
        assert err.to_payload() == {
            "code": err.code,
            "message": err.message,
            "data": None,
        }
