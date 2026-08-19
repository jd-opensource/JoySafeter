from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    DependencyDisposition,
)

# Closed sets shared with the frontend contract (parseReferencesResponse /
# SURFACE_LABEL_KEY). Keep in lockstep with the TS unions in
# frontend/hooks/managed/use-credential-references.ts.
ResourceType = Literal["agent", "trigger", "environment", "session"]
SurfaceCode = Literal[
    "agent_model_binding",
    "trigger_webhook_auth",
    "environment_injection",
    "active_session_snapshot",
]

# surface_id (scanner output) -> (resource_type, frontend surface code)
SURFACE_TO_TYPE: dict[str, tuple[ResourceType, SurfaceCode]] = {
    "live_agent_model_binding": ("agent", "agent_model_binding"),
    "trigger_webhook_auth_binding": ("trigger", "trigger_webhook_auth"),
    "live_environment_direct_injection": ("environment", "environment_injection"),
    "live_environment_http_egress_binding": ("environment", "environment_injection"),
    "active_session_model_environment_snapshot": ("session", "active_session_snapshot"),
    "session_credential_group_association": ("session", "active_session_snapshot"),
}


@dataclass(frozen=True, slots=True)
class ReferenceItem:
    surface: SurfaceCode
    resource_type: ResourceType
    id: str
    name: str | None


@dataclass(frozen=True, slots=True)
class ReferenceView:
    references: list[ReferenceItem]
    other_count: int
    can_archive: bool
    can_delete: bool


def _blocking_deps(
    deps: Sequence[CredentialDependency],
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> list[CredentialDependency]:
    return [dep for dep in deps if dep.blocks(archive_disp) or dep.blocks(delete_disp)]


def mappable_targets(
    deps: Sequence[CredentialDependency],
    *,
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> list[tuple[str, str]]:
    seen: dict[tuple[str, str], None] = {}
    for dep in _blocking_deps(deps, archive_disp, delete_disp):
        mapping = SURFACE_TO_TYPE.get(str(dep.surface_id))
        if mapping is None:
            continue
        resource_type, _surface = mapping
        seen[(resource_type, str(dep.source_id))] = None
    return list(seen.keys())


def build_reference_view(
    deps: Sequence[CredentialDependency],
    names: dict[tuple[str, str], str | None],
    *,
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> ReferenceView:
    blocking = _blocking_deps(deps, archive_disp, delete_disp)
    references: list[ReferenceItem] = []
    emitted: set[tuple[str, str]] = set()
    other: set[tuple[str, str]] = set()
    for dep in blocking:
        surface_id = str(dep.surface_id)
        source_id = str(dep.source_id)
        mapping = SURFACE_TO_TYPE.get(surface_id)
        if mapping is None:
            other.add((surface_id, source_id))
            continue
        resource_type, surface = mapping
        key = (resource_type, source_id)
        if key in emitted:
            continue
        emitted.add(key)
        references.append(
            ReferenceItem(
                surface=surface,
                resource_type=resource_type,
                id=source_id,
                name=names.get(key),
            )
        )
    can_archive = not any(dep.blocks(archive_disp) for dep in deps)
    can_delete = not any(dep.blocks(delete_disp) for dep in deps)
    return ReferenceView(
        references=references,
        other_count=len(other),
        can_archive=can_archive,
        can_delete=can_delete,
    )


async def resolve_reference_view(
    deps: Sequence[CredentialDependency],
    name_lookup,
    *,
    archive_disp: DependencyDisposition,
    delete_disp: DependencyDisposition,
) -> ReferenceView:
    """Resolve names for the mappable blocking deps and build the view.

    ``name_lookup`` is an async callable ``(resource_type, ids) -> {id: name}``;
    the caller binds ``project_id``. Written once here so the service (Task 3)
    and the coordinator (Task 6) share one name-resolution path.
    """
    targets = mappable_targets(deps, archive_disp=archive_disp, delete_disp=delete_disp)
    by_type: dict[str, list[str]] = {}
    for resource_type, source_id in targets:
        by_type.setdefault(resource_type, []).append(source_id)
    resource_types = list(by_type)
    resolved_per_type = await asyncio.gather(
        *(name_lookup(resource_type, by_type[resource_type]) for resource_type in resource_types)
    )
    names: dict[tuple[str, str], str | None] = {}
    for resource_type, resolved in zip(resource_types, resolved_per_type):
        for source_id in by_type[resource_type]:
            names[(resource_type, source_id)] = resolved.get(str(source_id))
    return build_reference_view(deps, names, archive_disp=archive_disp, delete_disp=delete_disp)
