from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ConfigurationIssue:
    provider_id: str
    field: str
    code: str
    message: str


class FederationConfigurationError(RuntimeError):
    def __init__(self, issues: Sequence[ConfigurationIssue]) -> None:
        self.issues = tuple(issues)
        rendered_issues = "; ".join(
            f"{issue.provider_id}.{issue.field}: {issue.code}: {issue.message}" for issue in self.issues
        )
        super().__init__(f"Federation configuration is invalid: {rendered_issues}")


class FederationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        user_action: str | None = None,
        data: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.user_action = user_action
        self.data = MappingProxyType(dict(data or {}))
        super().__init__(message)
