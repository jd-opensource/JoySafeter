"""
Copilot-specific exceptions for better error handling.

Provides specialized exception classes for Copilot operations,
enabling better error categorization and user-friendly error messages.
"""

from typing import Any

from fastapi import status

from app.common.exceptions import AppException, BadRequestException


class CopilotException(AppException):
    """Base exception for Copilot operations."""

    def __init__(
        self,
        message: str = "Copilot operation failed",
        *,
        code: int | None = 5001,
        data: Any = None,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ):
        super().__init__(status_code=status_code, message=message, code=code, data=data)


class CopilotLLMError(CopilotException):
    """LLM-related errors (API failures, rate limits, etc.)."""

    def __init__(
        self,
        message: str = "LLM service error",
        *,
        code: int | None = 5101,
        data: Any = None,
        original_error: Exception | None = None,
    ):
        if original_error:
            message = f"{message}: {str(original_error)}"
            if data is None:
                data = {"error_type": type(original_error).__name__}
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message=message,
            code=code,
            data=data,
        )


class CopilotValidationError(BadRequestException):
    """Action validation errors."""

    def __init__(
        self,
        message: str = "Action validation failed",
        *,
        code: int | None = 5102,
        data: Any = None,
    ):
        super().__init__(message=message, code=code, data=data)


class CopilotSessionError(CopilotException):
    """Session management errors (Redis unavailable, session not found, etc.)."""

    def __init__(
        self,
        message: str = "Session management error",
        *,
        code: int | None = 5103,
        data: Any = None,
        status_code: int = status.HTTP_503_SERVICE_UNAVAILABLE,
    ):
        super().__init__(
            status_code=status_code,
            message=message,
            code=code,
            data=data,
        )


class CopilotStreamError(CopilotException):
    """Streaming errors (connection issues, timeouts, etc.)."""

    def __init__(
        self,
        message: str = "Streaming error",
        *,
        code: int | None = 5104,
        data: Any = None,
    ):
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=message,
            code=code,
            data=data,
        )


class CopilotCredentialError(CopilotException):
    """Credential-related errors (missing API key, invalid credentials, etc.)."""

    def __init__(
        self,
        message: str = "Credential error",
        *,
        code: int | None = 5105,
        data: Any = None,
    ):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=message,
            code=code,
            data=data,
        )


class CopilotAgentError(CopilotException):
    """Agent execution errors (tool failures, recursion limits, etc.)."""

    def __init__(
        self,
        message: str = "Agent execution error",
        *,
        code: int | None = 5106,
        data: Any = None,
        original_error: Exception | None = None,
    ):
        if original_error:
            message = f"{message}: {str(original_error)}"
            if data is None:
                data = {"error_type": type(original_error).__name__}
        super().__init__(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=message,
            code=code,
            data=data,
        )
