"""Read-only credential-domain preflight inventory tests."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_environment import JoySafeterEnvironment
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    CredentialGroupId,
    CredentialId,
    EnvironmentId,
    OrganizationId,
    ProjectId,
    SessionId,
    TriggerId,
)

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "credential_preflight.py"
_SPEC = importlib.util.spec_from_file_location("credential_preflight", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
credential_preflight = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = credential_preflight
_SPEC.loader.exec_module(credential_preflight)

collect_credential_preflight = credential_preflight.collect_credential_preflight
serialize_report = credential_preflight.serialize_report
validate_report = credential_preflight.validate_report


def _new_organization(**values: Any) -> Organization:
    return Organization(id=OrganizationId.new(), **values)


def _new_project(**values: Any) -> Project:
    return Project(id=ProjectId.new(), **values)


def _new_credential(**values: Any) -> JoySafeterCredential:
    return JoySafeterCredential(id=CredentialId.new(), **values)


def _new_credential_group(**values: Any) -> JoySafeterCredentialGroup:
    return JoySafeterCredentialGroup(id=CredentialGroupId.new(), **values)


def _new_agent(**values: Any) -> JoySafeterAgent:
    return JoySafeterAgent(id=AgentId.new(), **values)


def _new_session(**values: Any) -> JoySafeterSession:
    return JoySafeterSession(id=SessionId.new(), **values)


def _new_trigger(**values: Any) -> JoySafeterTrigger:
    return JoySafeterTrigger(id=TriggerId.new(), **values)


def _new_environment(**values: Any) -> JoySafeterEnvironment:
    return JoySafeterEnvironment(id=EnvironmentId.new(), **values)


@pytest.mark.no_db
def test_cli_bootstraps_without_operator_secret_key():
    environment = os.environ.copy()
    environment.pop("SECRET_KEY", None)

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--help"],
        capture_output=True,
        env=environment,
        text=True,
    )

    assert result.returncode == 0, result.stderr


async def _project(db_session, label: str) -> ProjectId:
    organization = _new_organization(name=f"organization-{label}", slug=f"organization-{label}")
    db_session.add(organization)
    await db_session.flush()
    project = _new_project(org_id=organization.id, name=f"project-{label}", slug=f"project-{label}")
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _credential(db_session, project_id: ProjectId, label: str) -> JoySafeterCredential:
    credential = _new_credential(
        project_id=project_id,
        kind="model",
        name=f"credential-{label}",
        data={"API_KEY": "plaintext-must-never-appear"},
        provider="openai",
        protocol="openai",
        is_default=False,
    )
    db_session.add(credential)
    await db_session.flush()
    return credential


async def seed_session_with_unknown_snapshot_and_credential_ref(db_session) -> JoySafeterSession:
    agent = _new_agent(name="unscoped-agent", project_id=None)
    db_session.add(agent)
    await db_session.flush()
    session = _new_session(
        agent_id=agent.id,
        project_id=None,
        title="unscoped-session",
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.future",
            "model_credential_id": "01J000000000000000000CRED0",
        },
    )
    db_session.add(session)
    await db_session.commit()
    return session


@pytest.mark.asyncio
async def test_preflight_reports_unknown_snapshot_and_null_project_reference(db_session):
    await seed_session_with_unknown_snapshot_and_credential_ref(db_session)

    report = await collect_credential_preflight(db_session)

    assert report.snapshot_schema_counts["unknown"] == 1
    assert report.null_project_references[0]["surface"] == "session_snapshot"
    assert report.null_project_references[0]["field_path"] == "model_credential_id"


@pytest.mark.asyncio
async def test_unknown_agent_version_schema_is_inventory_only_and_session_schema_is_explicit_blocker(db_session):
    project_id = await _project(db_session, "snapshot-schemas")
    agent = _new_agent(name="snapshot-agent", project_id=project_id)
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        JoySafeterAgentVersion(
            id=AgentVersionId.new(),
            agent_id=agent.id,
            version=1,
            snapshot={"schema": "joysafeter.agent_execution_snapshot.future"},
        )
    )
    session = _new_session(
        agent_id=agent.id,
        project_id=project_id,
        title="unknown-session-snapshot",
        agent_snapshot={"schema": "joysafeter.agent_execution_snapshot.future"},
    )
    db_session.add(session)
    await db_session.commit()

    report = await collect_credential_preflight(db_session)

    assert report.snapshot_schema_counts["unknown"] == 2
    assert report.invalid_resources == (
        {
            "error_class": "UNKNOWN_ACTIVE_SESSION_SNAPSHOT_SCHEMA",
            "field_path": "schema",
            "resource_id": str(session.id),
            "surface": "session_snapshot",
        },
    )


@pytest.mark.asyncio
async def test_preflight_reports_trigger_reference_with_persisted_field_path(db_session):
    project_a = await _project(db_session, "trigger-a")
    project_b = await _project(db_session, "trigger-b")
    credential_b = await _credential(db_session, project_b, "trigger-b")
    agent = _new_agent(name="trigger-agent", project_id=project_a)
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        _new_trigger(
            name="credential-trigger",
            agent_id=agent.id,
            prompt_template="handle trigger",
            project_id=project_a,
            webhook_auth_credential_id=credential_b.id,
        )
    )
    await db_session.commit()

    report = await collect_credential_preflight(db_session)

    assert report.cross_project_references == (
        {
            "error_class": "CROSS_PROJECT_CREDENTIAL_REFERENCE",
            "field_path": "webhook_auth_credential_id",
            "resource_id": str(credential_b.id),
            "surface": "trigger",
        },
    )


def _run_cli(output_path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *arguments, "--output", str(output_path)],
        capture_output=True,
        env=os.environ.copy(),
        text=True,
    )


def test_cli_writes_clean_report_from_disposable_database(postgres_url, tmp_path):
    output_path = tmp_path / "clean-preflight.json"

    result = _run_cli(output_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(output_path.read_text())
    assert payload["invalid_resources"] == []
    assert payload["snapshot_schema_counts"] == {"legacy-v0": 0, "unknown": 0, "v1": 0, "v2": 0}


@pytest.mark.asyncio
async def test_cli_reports_active_session_schema_blocker_without_sensitive_values(db_session, postgres_url, tmp_path):
    project_id = await _project(db_session, "cli-blocker")
    credential = await _credential(db_session, project_id, "cli-blocker")
    agent = _new_agent(name="cli-blocker-agent", project_id=project_id)
    db_session.add(agent)
    await db_session.flush()
    session = _new_session(
        agent_id=agent.id,
        project_id=project_id,
        title="cli-blocker-session",
        agent_snapshot={
            "schema": "joysafeter.agent_execution_snapshot.future",
            "model_credential_id": str(credential.id),
            "unreported_sensitive_value": "cli-plaintext-must-never-appear",
        },
    )
    db_session.add(session)
    await db_session.commit()
    output_path = tmp_path / "blocker-preflight.json"

    result = _run_cli(output_path, "--fail-on-blocker")

    rendered = output_path.read_text()
    payload = json.loads(rendered)
    assert result.returncode == 1
    assert "UNKNOWN_ACTIVE_SESSION_SNAPSHOT_SCHEMA" in result.stderr
    assert "Event loop is closed" not in result.stderr
    assert payload["invalid_resources"] == [
        {
            "error_class": "UNKNOWN_ACTIVE_SESSION_SNAPSHOT_SCHEMA",
            "field_path": "schema",
            "resource_id": str(session.id),
            "surface": "session_snapshot",
        }
    ]
    assert "plaintext-must-never-appear" not in rendered
    assert "cli-plaintext-must-never-appear" not in rendered


@pytest.mark.asyncio
async def test_preflight_inventory_is_deterministic_and_redacts_material(db_session):
    project_a = await _project(db_session, "a")
    project_b = await _project(db_session, "b")
    credential_a = await _credential(db_session, project_a, "a")
    credential_b = await _credential(db_session, project_b, "b")

    group_a = _new_credential_group(project_id=project_a, name="group-a")
    group_b = _new_credential_group(project_id=project_a, name="group-b")
    db_session.add_all([group_a, group_b])
    await db_session.flush()
    db_session.add_all(
        [
            _new_credential(
                project_id=project_a,
                kind="mcp",
                name="mcp-a",
                data={"token_value": "ciphertext-must-never-appear"},
                mcp_server_url="https://mcp.example.test/sse",
                normalized_mcp_server_url="https://mcp.example.test/sse",
                credential_type="bearer",
                group_id=group_a.id,
            ),
            _new_credential(
                project_id=project_a,
                kind="mcp",
                name="mcp-b",
                data={"token_value": "masked-suffix-must-never-appear"},
                mcp_server_url="https://mcp.example.test/sse",
                normalized_mcp_server_url="https://mcp.example.test/sse",
                credential_type="static_bearer",
                group_id=group_b.id,
            ),
        ]
    )
    agent = _new_agent(name="agent-a", project_id=project_a)
    db_session.add(agent)
    await db_session.flush()
    db_session.add(
        JoySafeterAgentVersion(
            id=AgentVersionId.new(),
            agent_id=agent.id,
            version=1,
            snapshot={
                "schema": "joysafeter.agent_execution_snapshot.v1",
                "secret_ref": str(credential_a.id),
                "service_credential_id": str(credential_b.id),
            },
        )
    )
    db_session.add(
        _new_environment(
            project_id=project_a,
            name="environment-a",
            config={
                "secret_refs": [str(credential_a.id)],
                "egress_services": [{"service_credential_id": str(credential_b.id)}],
            },
        )
    )
    await db_session.commit()

    report = await collect_credential_preflight(db_session)
    rendered = serialize_report(report)

    validate_report(json.loads(rendered))
    assert report.credential_type_counts == {"bearer": 1, "static_bearer": 1}
    assert report.snapshot_schema_counts == {"legacy-v0": 0, "v1": 1, "v2": 0, "unknown": 0}
    assert report.legacy_reference_counts["agent_version.secret_ref"] == 1
    assert report.legacy_reference_counts["agent_version.service_credential_id"] == 1
    assert report.legacy_reference_counts["environment.secret_refs[]"] == 1
    assert report.legacy_reference_counts["environment.egress_services[].service_credential_id"] == 1
    assert report.cross_project_references == (
        {
            "error_class": "CROSS_PROJECT_CREDENTIAL_REFERENCE",
            "field_path": "service_credential_id",
            "resource_id": str(credential_b.id),
            "surface": "agent_version_snapshot",
        },
        {
            "error_class": "CROSS_PROJECT_CREDENTIAL_REFERENCE",
            "field_path": "config.egress_services[0].service_credential_id",
            "resource_id": str(credential_b.id),
            "surface": "environment",
        },
    )
    assert report.mcp_url_conflicts == (
        {
            "error_class": "MCP_NORMALIZED_URL_CONFLICT",
            "field_path": "normalized_mcp_server_url",
            "resource_id": str(group_a.id),
            "surface": "credential_group",
        },
        {
            "error_class": "MCP_NORMALIZED_URL_CONFLICT",
            "field_path": "normalized_mcp_server_url",
            "resource_id": str(group_b.id),
            "surface": "credential_group",
        },
    )
    assert "plaintext-must-never-appear" not in rendered
    assert "ciphertext-must-never-appear" not in rendered
    assert "masked-suffix-must-never-appear" not in rendered
    assert rendered == serialize_report(report)
