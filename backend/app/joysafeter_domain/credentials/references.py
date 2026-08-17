from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .types import (
    CredentialGroupId,
    CredentialId,
    ProjectId,
    require_identifier,
    require_non_empty_text,
    require_project_id,
)


class CredentialReferenceKind(StrEnum):
    RESOURCE = "resource"
    GROUP = "group"


@dataclass(frozen=True, slots=True)
class CredentialReference:
    kind: CredentialReferenceKind
    project_id: ProjectId
    source: str
    source_id: str
    credential_id: CredentialId | None
    group_id: CredentialGroupId | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", require_project_id(self.project_id))
        object.__setattr__(self, "source", require_non_empty_text(self.source, label="reference source"))
        object.__setattr__(self, "source_id", require_non_empty_text(self.source_id, label="reference source id"))
        if self.kind is CredentialReferenceKind.RESOURCE:
            if self.credential_id is None or self.group_id is not None:
                raise ValueError("resource references require only a credential id")
            require_identifier(self.credential_id, label="credential id")
        elif self.kind is CredentialReferenceKind.GROUP:
            if self.group_id is None or self.credential_id is not None:
                raise ValueError("group references require only a credential group id")
            require_identifier(self.group_id, label="credential group id")
        else:
            raise TypeError("credential reference kind is invalid")
