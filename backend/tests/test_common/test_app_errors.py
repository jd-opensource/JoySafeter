from app.common.app_errors import (
    AppError,
    DomainError,
    InfraError,
    PermissionDeniedError,
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
    assert err.code == "NODE_MODEL_NOT_CONFIGURED"


def test_validation_error_keeps_structured_data() -> None:
    err = ValidationError(
        code="REQUEST_INVALID",
        message="请求参数校验失败",
        data={"field": "workspace_id"},
    )

    assert err.to_payload()["data"] == {"field": "workspace_id"}
