"""Helpers for running JoySafeter as separate service roles."""

from __future__ import annotations

from enum import StrEnum

from app.joysafeter_shared.config.settings import settings


class ServiceRole(StrEnum):
    ALL = "all"
    API = "api"
    RUNNER = "runner"
    WORKER = "worker"


def current_role() -> ServiceRole:
    raw_role = (settings.service_role or ServiceRole.ALL.value).strip().lower()
    try:
        return ServiceRole(raw_role)
    except ValueError:
        allowed = ", ".join(role.value for role in ServiceRole)
        raise RuntimeError(f"Invalid JOYSAFETER_SERVICE_ROLE={raw_role!r}; expected one of: {allowed}")


def is_all_role() -> bool:
    return current_role() == ServiceRole.ALL


def is_api_role() -> bool:
    return current_role() in {ServiceRole.ALL, ServiceRole.API}


def is_runner_role() -> bool:
    return current_role() in {ServiceRole.ALL, ServiceRole.RUNNER}


def is_worker_role() -> bool:
    return current_role() in {ServiceRole.ALL, ServiceRole.WORKER}
