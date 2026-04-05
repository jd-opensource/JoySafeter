"""
Custom validators module

Provide enhanced parameter validation with detailed error messages.
"""

import re
from typing import Any

from pydantic import BaseModel, ConfigDict


class ValidationErrorDetail(BaseModel):
    """Validation error detail."""

    field: str
    message: str
    value: Any = None
    type: str = "validation_error"


class EnhancedBaseModel(BaseModel):
    """Enhanced base model with improved validation error handling."""

    model_config = ConfigDict(
        str_strip_whitespace=True,  # auto-strip leading/trailing whitespace
        validate_assignment=True,  # validate on assignment
    )


# password validator
def validate_password_strength(password: str, strict: bool = False) -> str:
    """Validate password strength."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if strict:
        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")

        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")

        if not re.search(r"\d", password):
            raise ValueError("Password must contain at least one digit")

        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            raise ValueError("Password must contain at least one special character")

    return password


def validate_username(username: str) -> str:
    """Validate username."""
    if not username:
        raise ValueError("Username must not be empty")

    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")

    if len(username) > 50:
        raise ValueError("Username must not exceed 50 characters")

    # only allow letters, digits, underscores, and hyphens
    if not re.match(r"^[a-zA-Z0-9_-]+$", username):
        raise ValueError("Username may only contain letters, digits, underscores, and hyphens")

    # must not start with a digit
    if username[0].isdigit():
        raise ValueError("Username must not start with a digit")

    return username


def validate_nickname(nickname: str) -> str:
    """Validate nickname."""
    if not nickname:
        raise ValueError("Nickname must not be empty")

    if len(nickname) < 2:
        raise ValueError("Nickname must be at least 2 characters")

    if len(nickname) > 50:
        raise ValueError("Nickname must not exceed 50 characters")

    # reject obviously dangerous characters
    if re.search(r'[<>"/\\|]', nickname):
        raise ValueError("Nickname contains illegal characters")

    return nickname


def validate_email_domain(email: str) -> str:
    """Validate email domain."""
    # reject common disposable email domains
    disposable_domains = [
        "10minutemail.com",
        "guerrillamail.com",
        "mailinator.com",
        "temp-mail.org",
        "throwaway.email",
        "yopmail.com",
    ]

    domain = email.split("@")[-1].lower()
    if domain in disposable_domains:
        raise ValueError("Disposable email addresses are not allowed")

    return email


def validate_thread_id(thread_id: str) -> str:
    """Validate conversation thread ID."""
    if not thread_id:
        raise ValueError("Thread ID must not be empty")

    # allow UUID format or other custom formats
    uuid_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    if not re.match(uuid_pattern, thread_id, re.IGNORECASE):
        raise ValueError("Thread ID format is invalid")

    return thread_id


def validate_temperature(temp: float) -> float:
    """Validate temperature parameter."""
    if not (0.0 <= temp <= 2.0):
        raise ValueError("Temperature must be between 0.0 and 2.0")

    return temp


def validate_max_tokens(tokens: int) -> int:
    """Validate max token count."""
    if tokens < 1:
        raise ValueError("Max tokens must be greater than 0")

    if tokens > 32768:  # upper limit for some models
        raise ValueError("Max tokens must not exceed 32768")

    return tokens


# enhanced field validators — use with Pydantic field_validator


def create_validation_error_response(errors: list) -> dict[str, Any]:
    """Create a validation error response."""
    return {
        "success": False,
        "code": 422,
        "message": "Request parameter validation failed",
        "errors": [
            ValidationErrorDetail(
                field=error["loc"][0] if error["loc"] else "unknown",
                message=error["msg"],
                value=error.get("input"),
                type=error["type"],
            ).model_dump()
            for error in errors
        ],
    }
