"""Per-sandbox resource-limit resolution (Foundation 3 — tenancy).

The effective CPU/memory ceiling for a sandbox is the owning project's override
when set, else the global default (``settings.sandbox_cpu`` /
``sandbox_memory_mb``). Resolved per-field so a project may override only CPU or
only memory. Kept as a plain function of the DB row + passed defaults — free of
the settings singleton — so it is trivially testable, mirroring
``resolve_project_task_limit``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project


@dataclass(frozen=True)
class SandboxResourceLimits:
    cpu: Optional[float]
    memory_mb: Optional[int]


async def resolve_project_sandbox_limits(
    db: AsyncSession,
    project_id: Optional[str],
    *,
    default_cpu: Optional[float],
    default_memory_mb: Optional[int],
) -> SandboxResourceLimits:
    """Effective (cpu, memory_mb) for a sandbox owned by ``project_id``.

    A ``None`` project (e.g. a project-agnostic warm-pool sandbox) or an unknown
    project falls back entirely to the global defaults. Otherwise each field is
    the project's override when set, else the default.
    """
    if project_id is None:
        return SandboxResourceLimits(cpu=default_cpu, memory_mb=default_memory_mb)

    row = (await db.execute(select(Project.max_cpu, Project.max_memory_mb).where(Project.id == project_id))).first()
    if row is None:
        return SandboxResourceLimits(cpu=default_cpu, memory_mb=default_memory_mb)

    project_cpu, project_memory_mb = row
    return SandboxResourceLimits(
        cpu=project_cpu if project_cpu is not None else default_cpu,
        memory_mb=project_memory_mb if project_memory_mb is not None else default_memory_mb,
    )
