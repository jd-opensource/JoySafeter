from __future__ import annotations

import uuid

import pytest

from app.core.agent.cli_backends.container_service import ContainerConfig, ContainerInfo
from app.core.agent.cli_backends.injectors import (
    CLISkillInjector,
    CredentialInjector,
    RuntimeConfigInjector,
)


# ---------------------------------------------------------------------------
# ContainerConfig / ContainerInfo data classes
# ---------------------------------------------------------------------------

def test_container_config_defaults():
    cfg = ContainerConfig()
    assert cfg.image == "joysafeter/cli-agent:latest"
    assert cfg.memory_limit == "2g"
    assert cfg.network_mode == "bridge"
    assert cfg.labels == {}


def test_container_config_custom():
    cfg = ContainerConfig(image="my-image:v1", memory_limit="4g", labels={"env": "test"})
    assert cfg.image == "my-image:v1"
    assert cfg.memory_limit == "4g"
    assert cfg.labels == {"env": "test"}


def test_container_info():
    info = ContainerInfo(
        container_id="abc123",
        name="cli-agent-test",
        status="running",
        working_dir="/workspace",
    )
    assert info.container_id == "abc123"
    assert info.name == "cli-agent-test"


# ---------------------------------------------------------------------------
# RuntimeConfigInjector._build_claude_md (pure logic, no Docker needed)
# ---------------------------------------------------------------------------

class _FakeContainerService:
    """Stub that records exec calls without touching Docker."""
    def __init__(self):
        self.calls: list[tuple[str, list[str]]] = []

    async def exec_in_container(self, container_id, cmd, workdir=None):
        self.calls.append((container_id, cmd))
        return ""


def test_build_claude_md_minimal():
    injector = RuntimeConfigInjector(_FakeContainerService())
    md = injector._build_claude_md()
    assert "# Agent Configuration" in md
    assert "autonomous coding agent" in md
    assert "## Instructions" not in md
    assert "## Available Skills" not in md
    assert "## Project Context" not in md


def test_build_claude_md_with_instructions():
    injector = RuntimeConfigInjector(_FakeContainerService())
    md = injector._build_claude_md(instructions="Always write tests first.")
    assert "## Instructions" in md
    assert "Always write tests first." in md


def test_build_claude_md_with_skills():
    injector = RuntimeConfigInjector(_FakeContainerService())
    md = injector._build_claude_md(skill_names=["code_review", "deploy"])
    assert "## Available Skills" in md
    assert "- code_review" in md
    assert "- deploy" in md


def test_build_claude_md_with_project_context():
    injector = RuntimeConfigInjector(_FakeContainerService())
    md = injector._build_claude_md(project_context="Python 3.12, FastAPI backend")
    assert "## Project Context" in md
    assert "Python 3.12, FastAPI backend" in md


def test_build_claude_md_full():
    injector = RuntimeConfigInjector(_FakeContainerService())
    md = injector._build_claude_md(
        instructions="Be thorough.",
        skill_names=["lint", "test"],
        project_context="Monorepo with backend/ and frontend/",
    )
    assert "## Instructions" in md
    assert "Be thorough." in md
    assert "## Available Skills" in md
    assert "- lint" in md
    assert "- test" in md
    assert "## Project Context" in md
    assert "Monorepo" in md


# ---------------------------------------------------------------------------
# Async injector tests (using fake container service)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credential_injector_build_env():
    injector = CredentialInjector()
    env = injector.build_env({"ANTHROPIC_API_KEY": "sk-test", "GITHUB_TOKEN": "ghp-abc"})
    assert env == {"ANTHROPIC_API_KEY": "sk-test", "GITHUB_TOKEN": "ghp-abc"}


@pytest.mark.asyncio
async def test_credential_injector_empty():
    injector = CredentialInjector()
    env = injector.build_env({})
    assert env == {}


@pytest.mark.asyncio
async def test_skill_injector_inject():
    svc = _FakeContainerService()
    injector = CLISkillInjector(svc)
    skills = [
        {"name": "lint", "command": "ruff check ."},
        {"name": "test", "command": "pytest"},
    ]
    await injector.inject("ctr-2", skills)
    # 1 mkdir + 2 skill writes
    assert len(svc.calls) == 3
    assert svc.calls[0][1] == ["mkdir", "-p", "/workspace/.skills"]


@pytest.mark.asyncio
async def test_skill_injector_empty():
    svc = _FakeContainerService()
    injector = CLISkillInjector(svc)
    await injector.inject("ctr-2", [])
    assert len(svc.calls) == 0


@pytest.mark.asyncio
async def test_runtime_config_injector_inject():
    svc = _FakeContainerService()
    injector = RuntimeConfigInjector(svc)
    await injector.inject(
        "ctr-3",
        instructions="Write clean code.",
        skill_names=["lint"],
        working_dir="/project",
    )
    assert len(svc.calls) == 1
    container_id, cmd = svc.calls[0]
    assert container_id == "ctr-3"
    cmd_str = " ".join(cmd)
    assert "/project/CLAUDE.md" in cmd_str
