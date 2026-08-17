from __future__ import annotations

from app.joysafeter_infrastructure.sensitive_material.legacy_v1 import LegacyV1MaterialProtector


class RepositoryAccessMaterialAdapter:
    def __init__(self, protector: LegacyV1MaterialProtector) -> None:
        self._protector = protector

    def protect_repository_token(self, value: str) -> str:
        if not value:
            raise ValueError("repository token must be non-empty")
        return self._protector.protect(value)

    def reveal_repository_token(self, value: str) -> str:
        return self._protector.reveal(value)
