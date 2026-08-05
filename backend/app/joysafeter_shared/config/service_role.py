"""Helpers for running JoySafeter Python service roles."""

from __future__ import annotations

from enum import StrEnum

from app.joysafeter_shared.config.settings import settings


class ServiceRole(StrEnum):
    API = "api"
    WORKER = "worker"


def current_role() -> ServiceRole:
    raw_role = (settings.service_role or ServiceRole.API.value).strip().lower()
    try:
        return ServiceRole(raw_role)
    except ValueError:
        allowed = ", ".join(role.value for role in ServiceRole)
        raise RuntimeError(f"Invalid JOYSAFETER_SERVICE_ROLE={raw_role!r}; expected one of: {allowed}")


def is_api_role() -> bool:
    return current_role() == ServiceRole.API


def is_worker_role() -> bool:
    return current_role() == ServiceRole.WORKER
