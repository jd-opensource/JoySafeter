from typing import Any, Mapping

from app.common.app_errors import AuthenticationError, InfraError, InternalServiceError, InvalidRequestError


def _with_original_error(data: Mapping[str, Any] | None, original_error: Exception | None) -> dict[str, Any] | None:
    payload = dict(data) if data else None
    if original_error is None:
        return payload
    merged = payload or {}
    merged["error_type"] = type(original_error).__name__
    merged["error_message"] = str(original_error)
    return merged


class CopilotLLMError(InfraError):
    def __init__(
        self,
        message: str = "LLM service error",
        *,
        code: str = "COPILOT_LLM_ERROR",
        data: Mapping[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(code=code, message=message, data=_with_original_error(data, original_error))


class CopilotValidationError(InvalidRequestError):
    def __init__(
        self,
        message: str = "Action validation failed",
        *,
        code: str = "COPILOT_VALIDATION_ERROR",
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, data=data)


class CopilotSessionError(InfraError):
    def __init__(
        self,
        message: str = "Session management error",
        *,
        code: str = "COPILOT_SESSION_ERROR",
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code=code, message=message, data=dict(data) if data else None)


class CopilotCredentialError(AuthenticationError):
    def __init__(
        self,
        message: str = "Credential error",
        *,
        code: str = "COPILOT_CREDENTIAL_ERROR",
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message=message, code=code, data=data)


class CopilotAgentError(InternalServiceError):
    def __init__(
        self,
        message: str = "Agent execution error",
        *,
        code: str = "COPILOT_AGENT_ERROR",
        data: Mapping[str, Any] | None = None,
        original_error: Exception | None = None,
    ) -> None:
        super().__init__(message=message, code=code, data=_with_original_error(data, original_error))
