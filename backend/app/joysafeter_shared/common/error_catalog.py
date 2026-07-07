from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from app.joysafeter_shared.common.app_errors import AppError


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    code: str
    error_class: Type[AppError]
    default_message: str
    retryable: bool = False
    user_action: str | None = None
    data_fields: tuple[str, ...] = field(default=())


# Populated in Task 1.2 by the seeding generator, then hand-maintained.
CATALOG: dict[str, CatalogEntry] = {}


def is_registered(code: str) -> bool:
    return code in CATALOG


def entry_for(code: str) -> CatalogEntry | None:
    return CATALOG.get(code)


def all_codes() -> frozenset[str]:
    return frozenset(CATALOG)
