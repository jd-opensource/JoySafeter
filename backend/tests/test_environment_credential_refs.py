"""Service-level tests for Task 9c: an Environment references service credentials
by stable id (was name-based ``credential_ref``/``secret_refs``).

Real-DB tests via conftest's ``db_session``: the CredentialService kind check is
enforced against Postgres. The full app is intentionally un-loadable mid-cutover,
so everything here runs at the service/route-helper level (no TestClient).
"""

import uuid

import pytest
import pytest_asyncio

from app.joysafeter_api.api.v1.environments import _validate_secret_refs
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    EnvironmentSecretReference,
    extract_environment_secret_references,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import CredentialId


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"proj-{uuid.uuid4()}", slug=f"proj-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest_asyncio.fixture
async def project_id(db_session) -> str:
    return await _make_project(db_session)


async def _make_service_credential(db_session, project_id: str) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(kind="service", name=f"s-{uuid.uuid4()}", data={"TOKEN": "t"}),
        project_id=project_id,
    )
    return cred.id


async def _make_model_credential(db_session, project_id: str) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="model",
            name=f"m-{uuid.uuid4()}",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "sk-secret"},
        ),
        project_id=project_id,
    )
    return cred.id


def _egress_config(service_credential_id: CredentialId) -> EnvironmentConfig:
    return EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api/",
                "service_credential_id": str(service_credential_id),
                "inject": {"type": "bearer", "secret_key": "ACCESS_TOKEN"},
            }
        ]
    )


@pytest.mark.asyncio
async def test_create_environment_with_valid_service_credential_persists(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    config = _egress_config(cred_id)
    await _validate_secret_refs(db_session, config, project_id)

    svc = EnvironmentService(db_session)
    env = await svc.create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=config),
        project_id=project_id,
    )

    stored = env.config["egress_services"][0]["service_credential_id"]
    assert stored == str(cred_id)
    assert "credential_ref" not in env.config["egress_services"][0]


@pytest.mark.asyncio
async def test_validate_rejects_nonexistent_credential(db_session, project_id):
    config = _egress_config(CredentialId.new())
    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, config, project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_validate_rejects_non_service_credential_kind(db_session, project_id):
    model_cred_id = await _make_model_credential(db_session, project_id)
    config = _egress_config(model_cred_id)
    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, config, project_id)
    assert exc.value.code == "CREDENTIAL_KIND_INVALID"


@pytest.mark.asyncio
async def test_validate_rejects_credential_from_other_project(db_session, project_id):
    other_project = await _make_project(db_session)
    other_cred_id = await _make_service_credential(db_session, other_project)
    config = _egress_config(other_cred_id)
    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, config, project_id)
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_validate_secret_refs_direct_source(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    config = EnvironmentConfig(secret_refs=[str(cred_id)])
    await _validate_secret_refs(db_session, config, project_id)


def test_extract_environment_secret_references_from_both_sources():
    direct_id = CredentialId.new()
    egress_id = CredentialId.new()
    config = EnvironmentConfig(
        secret_refs=[str(direct_id)],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api/",
                "service_credential_id": str(egress_id),
            }
        ],
    )

    assert extract_environment_secret_references(config) == [
        EnvironmentSecretReference(direct_id, "secret_refs"),
        EnvironmentSecretReference(egress_id, "egress_services"),
    ]
