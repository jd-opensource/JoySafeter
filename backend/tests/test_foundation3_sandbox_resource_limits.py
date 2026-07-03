"""Foundation 3 (tenancy) — per-sandbox resource limits (CPU / memory).

Every Docker sandbox must run under a CPU/memory ceiling so one tenant's agent
cannot exhaust host resources on the shared fleet (noisy-neighbor / resource
exhaustion). The effective limit is the project's override when set, else the
global default; resolved per-field so a project may override only CPU or only
memory. The Docker provider translates the resolved limit into HostConfig
NanoCpus / Memory.
"""

import uuid

import pytest

from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_orchestrator.sandbox.resource_limits import (
    SandboxResourceLimits,
    resolve_project_sandbox_limits,
)


async def _make_project(db_session, *, max_cpu=None, max_memory_mb=None) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(
        org_id=org.id,
        name=f"proj-{uuid.uuid4()}",
        slug=f"proj-{uuid.uuid4()}",
        max_cpu=max_cpu,
        max_memory_mb=max_memory_mb,
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.mark.asyncio
async def test_no_project_uses_global_defaults(db_session):
    limits = await resolve_project_sandbox_limits(db_session, None, default_cpu=2.0, default_memory_mb=4096)
    assert limits == SandboxResourceLimits(cpu=2.0, memory_mb=4096)


@pytest.mark.asyncio
async def test_unknown_project_uses_global_defaults(db_session):
    limits = await resolve_project_sandbox_limits(
        db_session, str(uuid.uuid4()), default_cpu=2.0, default_memory_mb=4096
    )
    assert limits == SandboxResourceLimits(cpu=2.0, memory_mb=4096)


@pytest.mark.asyncio
async def test_project_without_override_uses_defaults(db_session):
    project_id = await _make_project(db_session)
    limits = await resolve_project_sandbox_limits(db_session, project_id, default_cpu=2.0, default_memory_mb=4096)
    assert limits == SandboxResourceLimits(cpu=2.0, memory_mb=4096)


@pytest.mark.asyncio
async def test_project_overrides_both_fields(db_session):
    project_id = await _make_project(db_session, max_cpu=8.0, max_memory_mb=16384)
    limits = await resolve_project_sandbox_limits(db_session, project_id, default_cpu=2.0, default_memory_mb=4096)
    assert limits == SandboxResourceLimits(cpu=8.0, memory_mb=16384)


@pytest.mark.asyncio
async def test_project_overrides_one_field_only(db_session):
    # Only CPU overridden -> memory still falls back to the global default.
    project_id = await _make_project(db_session, max_cpu=8.0)
    limits = await resolve_project_sandbox_limits(db_session, project_id, default_cpu=2.0, default_memory_mb=4096)
    assert limits == SandboxResourceLimits(cpu=8.0, memory_mb=4096), (
        "an unset field must fall back to the default independently"
    )


# --- Docker provider: the resolved limit must land in the container HostConfig.


class _FakeContainer:
    async def start(self) -> None:
        pass


class _FakeContainers:
    def __init__(self) -> None:
        self.created_config: dict | None = None

    async def create_or_replace(self, name: str, config: dict) -> _FakeContainer:
        self.created_config = config
        return _FakeContainer()


class _FakeDocker:
    def __init__(self) -> None:
        self.containers = _FakeContainers()


async def _make_provider_with_fake_docker():
    from app.joysafeter_orchestrator.sandbox.docker_provider import DockerSandboxProvider

    provider = DockerSandboxProvider()
    await provider._docker.close()  # close the real (unused) aiodocker client
    fake = _FakeDocker()
    provider._docker = fake  # type: ignore[assignment]
    return provider, fake


@pytest.mark.asyncio
async def test_docker_create_applies_cpu_and_memory_limits():
    provider, fake = await _make_provider_with_fake_docker()
    await provider.create(name="s1", image="img", env={}, work_dir="", labels={}, cpu=2.0, memory_mb=4096)
    host_config = fake.containers.created_config["HostConfig"]
    assert host_config["NanoCpus"] == int(2.0 * 1e9), "cpu cores must map to NanoCpus"
    assert host_config["Memory"] == 4096 * 1024 * 1024, "memory_mb must map to Memory bytes"


@pytest.mark.asyncio
async def test_docker_create_omits_limits_when_none():
    provider, fake = await _make_provider_with_fake_docker()
    await provider.create(name="s1", image="img", env={}, work_dir="", labels={}, cpu=None, memory_mb=None)
    host_config = fake.containers.created_config["HostConfig"]
    assert "NanoCpus" not in host_config, "no CPU limit must be set when cpu is None"
    assert "Memory" not in host_config, "no memory limit must be set when memory_mb is None"
