from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from app.joysafeter_application.credentials.composition import (
    compose_credential_application,
    compose_repository_access_material_adapter,
    compose_task_identity_material_adapter,
)
from app.joysafeter_domain.credentials import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    EngineKind,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ProjectId,
    WebhookAuthBinding,
)
from app.joysafeter_domain.credentials.bindings import (
    EgressInjectKind,
    EgressInjectPolicy,
    WebhookAuthMethod,
)
from app.joysafeter_domain.credentials.types import NormalizedEndpoint
from app.joysafeter_domain.llm.model_inference_policy import build_model_inference_policy
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import (
    AddGroupCredentialRequest,
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
)
from app.joysafeter_shared.config.settings import joysafeter_config

RUST_KERNEL = Path(__file__).resolve().parents[1] / "app/joysafeter_orchestrator_rs/src/kernel"


async def _project(db_session) -> str:
    organization = Organization(name=f"runtime-{uuid.uuid4()}", slug=f"runtime-{uuid.uuid4()}")
    db_session.add(organization)
    await db_session.flush()
    project = Project(
        org_id=organization.id,
        name=f"runtime-{uuid.uuid4()}",
        slug=f"runtime-{uuid.uuid4()}",
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.mark.asyncio
async def test_runtime_binding_matrix_limits_material_to_each_consumer(db_session) -> None:
    project_id = await _project(db_session)
    application = compose_credential_application(db_session)
    model = await application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="runtime-model",
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "model-secret", "OPENAI_BASE_URL": "https://api.openai.com"},
        ),
        project_id=project_id,
    )
    service = await application.resource_service.create(
        CreateCredentialRequest(
            kind="service",
            name="runtime-service",
            data={"HTTP_TOKEN": "http-secret", "WEBHOOK_SECRET": "webhook-secret", "ENV_ONLY": "env-secret"},
        ),
        project_id=project_id,
    )

    model_binding = build_model_inference_policy(
        application.binding_service._catalog,
        project_id=ProjectId(project_id),
        credential_id=CredentialId(str(model.id)),
        engine_kind=EngineKind.CODEX,
        model_id="gpt-5",
    )
    validated_model, _ = await application.binding_service.validate_model_inference(model_binding)
    model_material = await application.material_adapter.load(validated_model)

    http_binding = HttpEgressBinding(
        ProjectId(project_id),
        CredentialId(str(service.id)),
        NormalizedEndpoint("https://example.com/api"),
        EgressInjectPolicy(EgressInjectKind.BEARER, CredentialFieldName("HTTP_TOKEN")),
    )
    webhook_binding = WebhookAuthBinding(
        ProjectId(project_id),
        CredentialId(str(service.id)),
        CredentialFieldName("WEBHOOK_SECRET"),
        frozenset({WebhookAuthMethod.BEARER}),
    )
    environment_binding = EnvironmentInjectionBinding(
        ProjectId(project_id),
        CredentialId(str(service.id)),
    )

    http_material = await application.material_adapter.load(await application.binding_service.validate(http_binding))
    webhook_material = await application.material_adapter.load(
        await application.binding_service.validate(webhook_binding)
    )
    environment_material = await application.material_adapter.load(
        await application.binding_service.validate(environment_binding)
    )

    assert dict(model_material.fields) == {
        CredentialFieldName("OPENAI_API_KEY"): "model-secret",
        CredentialFieldName("OPENAI_BASE_URL"): "https://api.openai.com",
    }
    assert dict(http_material.fields) == {CredentialFieldName("HTTP_TOKEN"): "http-secret"}
    assert dict(webhook_material.fields) == {CredentialFieldName("WEBHOOK_SECRET"): "webhook-secret"}
    assert dict(environment_material.fields) == {
        CredentialFieldName("HTTP_TOKEN"): "http-secret",
        CredentialFieldName("WEBHOOK_SECRET"): "webhook-secret",
        CredentialFieldName("ENV_ONLY"): "env-secret",
    }
    assert "secret" not in repr(model_material)
    assert "secret" not in repr(http_material)
    assert "secret" not in repr(webhook_material)
    assert "secret" not in repr(environment_material)


@pytest.mark.asyncio
async def test_mcp_group_validates_live_member_without_exposing_token(db_session) -> None:
    project_id = await _project(db_session)
    application = compose_credential_application(db_session)
    group = await application.group_service.create(
        CreateCredentialGroupRequest(name="runtime-mcp-group"),
        project_id,
    )
    member = await application.group_service.add_credential(
        group.id,
        AddGroupCredentialRequest(
            name="runtime-mcp",
            mcp_server_url="https://mcp.example.com",
            data={"token_value": "mcp-secret"},
        ),
        project_id,
    )

    await application.group_service.validate_binding(
        McpGroupBinding(
            ProjectId(project_id),
            (CredentialGroupId(str(group.id)),),
            (),
        )
    )

    assert member.data["token_value"].startswith("enc:v1:")
    assert "mcp-secret" not in repr(member)


def test_repository_and_task_identity_material_stay_in_purpose_adapters() -> None:
    repository = compose_repository_access_material_adapter(joysafeter_config.vault_encryption_key)
    identity = compose_task_identity_material_adapter(joysafeter_config.vault_encryption_key)

    repository_ciphertext = repository.protect_repository_token("repository-secret")
    identity_ciphertext = identity.protect_identity_credential("identity-secret")

    assert repository_ciphertext.startswith("enc:v1:")
    assert identity_ciphertext.startswith("enc:v1:")
    assert repository.reveal_repository_token(repository_ciphertext) == "repository-secret"
    assert identity.reveal_identity_credential(identity_ciphertext) == "identity-secret"


def test_sandbox_runtime_only_exports_explicit_environment_credentials() -> None:
    resolver = (RUST_KERNEL / "sandbox_resolver.rs").read_text()

    assert "for credential_id in environment_credential_ids(&environment.config)?" in resolver
    assert "let Some(key_value) = env.remove(credential_key.key)" in resolver
    assert (
        "never in sandbox env/secrets"
        in (
            Path(__file__).resolve().parents[1]
            / "app/joysafeter_orchestrator_rs/crates/agent-identity-trait/src/lib.rs"
        ).read_text()
    )
