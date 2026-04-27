from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ErrorSource = Literal[
    "api",
    "engine",
    "runtime",
    "node",
    "tool",
    "websocket",
    "auth",
    "validation",
    "permission",
    "internal",
]

UserAction = Literal[
    "retry",
    "configure_model",
    "relogin",
    "fix_input",
    "contact_support",
]


@dataclass(slots=True)
class ErrorDescriptor:
    code: str
    message: str
    source: ErrorSource
    retryable: bool
    detail: str | None = None
    user_action: UserAction | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, http_status: int | None = None) -> dict[str, Any]:
        context = dict(self.context)
        if http_status is not None:
            context["http_status"] = http_status
        payload: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "retryable": self.retryable,
        }
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.user_action is not None:
            payload["user_action"] = self.user_action
        if context:
            payload["context"] = context
        return payload
