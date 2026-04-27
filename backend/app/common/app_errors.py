from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AppError(Exception):
    code: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.message)

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "data": dict(self.data),
        }


class DomainError(AppError):
    pass


class InfraError(AppError):
    pass


class ValidationError(AppError):
    pass


class PermissionDeniedError(AppError):
    pass
