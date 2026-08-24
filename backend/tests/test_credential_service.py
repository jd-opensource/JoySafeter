"""Tests for the unified CredentialService (Task 5).

These are real-DB tests (Postgres via conftest's db_session): the service relies
on the DB's partial unique indexes (project,kind,name), the kind CHECK, and
FOR UPDATE row locks, so sqlite is not a substitute.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.joysafeter_application.credentials.application_service import CredentialService
from app.joysafeter_application.credentials.binding_service import BindingIssuanceAuthority
from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.credentials.types import ProjectId
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_infrastructure.credentials.material_adapter import ManagedCredentialMaterialAdapter
from app.joysafeter_infrastructure.credentials.sqlalchemy_repository import SqlAlchemyCredentialRepository
from app.joysafeter_infrastructure.sensitive_material.versioned import VersionedMaterialProtector
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_shared.security.credential_cipher import CredentialCiphertextError


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


@pytest.mark.asyncio
async def test_create_model_requires_provider_protocol(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    with pytest.raises(AppError) as exc:
        await svc.create(
            CreateCredentialRequest(kind="model", name="m1", data={"API_KEY": "sk-1"}),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_create_model_ok(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="m1",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "sk-secret"},
        ),
        project_id=project_id,
    )
    assert cred.kind == "model"
    assert cred.provider == "openai"
    # Stored value is encrypted, not plaintext.
    assert cred.data["API_KEY"].startswith("enc:v1:")


@pytest.mark.asyncio
async def test_repository_read_paths_reject_non_object_persisted_material(db_session, project_id):
    service = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await service.create(
        CreateCredentialRequest(kind="service", name="invalid-shape", data={"TOKEN": "secret"}),
        project_id=project_id,
    )
    stored_credential_id = credential.id
    await db_session.execute(
        text("UPDATE joysafeter_credentials SET data = '[]'::jsonb WHERE id = :id"),
        {"id": stored_credential_id.uuid},
    )
    await db_session.commit()
    db_session.expire_all()

    authority = BindingIssuanceAuthority()
    material = ManagedCredentialMaterialAdapter(
        None,
        VersionedMaterialProtector(joysafeter_config.vault_encryption_key),
        authority,
    )
    repository = SqlAlchemyCredentialRepository(db_session, material=material)
    material.bind_repository(repository)
    credential_id = DomainCredentialId(str(stored_credential_id))
    domain_project_id = ProjectId(project_id)

    with pytest.raises(CredentialCiphertextError, match="data must be a JSON object"):
        await repository.get_resource(credential_id, domain_project_id)
    with pytest.raises(CredentialCiphertextError, match="data must be a JSON object"):
        await repository.load_encrypted_material(credential_id, domain_project_id)

    stored = await repository.get(stored_credential_id, project_id)
    assert stored is not None
    with pytest.raises(CredentialCiphertextError, match="data must be a JSON object"):
        repository.get_masked(stored)


@pytest.mark.no_db
def test_decrypt_data_rejects_non_string_storage_without_coercion():
    material = ManagedCredentialMaterialAdapter(
        None,
        VersionedMaterialProtector(joysafeter_config.vault_encryption_key),
        BindingIssuanceAuthority(),
    )
    repository = SqlAlchemyCredentialRepository(None, material=material)  # type: ignore[arg-type]

    with pytest.raises(CredentialCiphertextError, match="must be a string"):
        repository.decrypt_data({"API_KEY": 123})


@pytest.mark.asyncio
async def test_name_unique_per_kind(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    await svc.create(
        CreateCredentialRequest(kind="service", name="dup", data={"TOKEN": "a"}),
        project_id=project_id,
    )
    # Same kind + name -> conflict.
    with pytest.raises(AppError) as exc:
        await svc.create(
            CreateCredentialRequest(kind="service", name="dup", data={"TOKEN": "b"}),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_NAME_EXISTS"
    # Different kind, same name -> OK.
    cred = await svc.create(
        CreateCredentialRequest(kind="model", name="dup", provider="openai", protocol="openai", data={"API_KEY": "x"}),
        project_id=project_id,
    )
    assert cred.name == "dup"


@pytest.mark.asyncio
async def test_service_create_rejects_provider(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    with pytest.raises(AppError) as exc:
        await svc.create(
            CreateCredentialRequest(kind="service", name="s1", provider="openai", data={"TOKEN": "a"}),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_FIELD_INVALID"


@pytest.mark.asyncio
async def test_update_preserves_masked_value(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model", name="m1", provider="openai", protocol="openai", data={"API_KEY": "sk-supersecret"}
        ),
        project_id=project_id,
    )
    masked = svc.get_masked(cred)
    # Re-submit the masked value for API_KEY -> original must be preserved.
    updated = await svc.update(
        cred.id,
        UpdateCredentialRequest(data={"API_KEY": masked["API_KEY"]}),
        project_id=project_id,
    )
    plain = svc.get_credential_data(updated)
    assert plain["API_KEY"] == "sk-supersecret"


@pytest.mark.asyncio
async def test_get_masked_masks_sensitive(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="m1",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "sk-supersecret", "BASE_URL": "https://api.example.com"},
        ),
        project_id=project_id,
    )
    masked = svc.get_masked(cred)
    assert masked["API_KEY"].startswith("********")
    assert "supersecret" not in masked["API_KEY"]
    assert masked["BASE_URL"] == "https://api.example.com"


def test_get_masked_does_not_decrypt_corrupt_ciphertext():
    repository = __import__(
        "app.joysafeter_infrastructure.credentials.sqlalchemy_repository",
        fromlist=["SqlAlchemyCredentialRepository"],
    ).SqlAlchemyCredentialRepository.__new__(
        __import__(
            "app.joysafeter_infrastructure.credentials.sqlalchemy_repository",
            fromlist=["SqlAlchemyCredentialRepository"],
        ).SqlAlchemyCredentialRepository
    )
    credential = type("Credential", (), {"data": {"TOKEN": "not-valid-ciphertext"}})()

    assert repository.get_masked(credential) == {"TOKEN": "********"}


@pytest.mark.asyncio
async def test_get_masked_sanitizes_display_url_credentials_and_query(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    credential = await svc.create(
        CreateCredentialRequest(
            kind="service",
            name="url-display",
            data={"BASE_URL": "https://user:password@example.com/path?token=secret#fragment"},
        ),
        project_id=project_id,
    )

    assert svc.get_masked(credential)["BASE_URL"] == "https://example.com/path"


@pytest.mark.asyncio
async def test_kind_immutable(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(kind="service", name="s1", data={"TOKEN": "a"}),
        project_id=project_id,
    )
    # UpdateCredentialRequest has no `kind` field (extra="forbid"); passing it fails
    # at the schema boundary, proving kind cannot be changed through update.
    with pytest.raises(Exception):
        UpdateCredentialRequest(kind="model")  # type: ignore[call-arg]
    # And a normal update leaves kind unchanged.
    updated = await svc.update(cred.id, UpdateCredentialRequest(name="s1-renamed"), project_id=project_id)
    assert updated.kind == "service"


@pytest.mark.asyncio
async def test_data_contract_rejects_oversize(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    with pytest.raises(AppError) as exc:
        await svc.create(
            CreateCredentialRequest(kind="service", name="s1", data={"TOKEN": "x" * 9000}),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_FIELD_INVALID"


@pytest.mark.asyncio
async def test_data_contract_rejects_too_many_fields(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    big = {f"K{i}": "v" for i in range(60)}
    with pytest.raises(AppError) as exc:
        await svc.create(
            CreateCredentialRequest(kind="service", name="s1", data=big),
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_FIELD_INVALID"


@pytest.mark.asyncio
async def test_set_and_clear_default(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    a = await svc.create(
        CreateCredentialRequest(kind="model", name="a", provider="openai", protocol="openai", data={"API_KEY": "1"}),
        project_id=project_id,
    )
    b = await svc.create(
        CreateCredentialRequest(kind="model", name="b", provider="openai", protocol="openai", data={"API_KEY": "2"}),
        project_id=project_id,
    )
    await svc.set_default(a.id, project_id=project_id)
    a = await svc.get(a.id, project_id=project_id)
    assert a.is_default is True
    # Setting b default clears a (same protocol).
    await svc.set_default(b.id, project_id=project_id)
    a = await svc.get(a.id, project_id=project_id)
    b = await svc.get(b.id, project_id=project_id)
    assert a.is_default is False
    assert b.is_default is True
    await svc.clear_default(b.id, project_id=project_id)
    b = await svc.get(b.id, project_id=project_id)
    assert b.is_default is False


@pytest.mark.asyncio
async def test_set_default_rejects_archived_credential_without_clearing_active_default(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    active = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="active",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "1"},
        ),
        project_id=project_id,
    )
    archived = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="archived",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "2"},
        ),
        project_id=project_id,
    )
    active_id = active.id
    archived_id = archived.id
    await svc.set_default(active_id, project_id=project_id)
    await svc.archive(archived_id, project_id=project_id)

    with pytest.raises(AppError) as exc:
        await svc.set_default(archived_id, project_id=project_id)

    assert exc.value.code == "CREDENTIAL_ARCHIVED"
    assert (await svc.get(active_id, project_id=project_id)).is_default is True


@pytest.mark.asyncio
async def test_lifecycle_archive_restore_soft_delete(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(kind="service", name="s1", data={"TOKEN": "a"}),
        project_id=project_id,
    )
    await svc.archive(cred.id, project_id=project_id)
    cred = await svc.get(cred.id, project_id=project_id)
    assert cred.archived_at is not None
    await svc.restore(cred.id, project_id=project_id)
    cred = await svc.get(cred.id, project_id=project_id)
    assert cred.archived_at is None
    await svc.soft_delete(cred.id, project_id=project_id)
    stored = (
        await db_session.execute(
            select(JoySafeterCredential.data, JoySafeterCredential.material_erased_at).where(
                JoySafeterCredential.id == cred.id
            )
        )
    ).one()
    assert stored.data == {}
    assert stored.material_erased_at is not None
    # Soft-deleted credentials are not returned by get().
    assert await svc.get(cred.id, project_id=project_id) is None


@pytest.mark.asyncio
async def test_archived_resource_rejects_update_and_default_mutation(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="archived-matrix",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    credential_id = cred.id
    await svc.archive(credential_id, project_id=project_id)

    for operation in (
        lambda: svc.update(
            credential_id,
            UpdateCredentialRequest(name="must-not-change"),
            project_id=project_id,
        ),
        lambda: svc.clear_default(credential_id, project_id=project_id),
    ):
        with pytest.raises(AppError) as exc:
            await operation()
        assert exc.value.code == "CREDENTIAL_ARCHIVED"


@pytest.mark.asyncio
async def test_deleted_resource_rejects_patch_and_default_mutation_without_clearing_live_default(
    db_session, project_id
):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    live_default = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="live-default",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "live"},
            is_default=True,
        ),
        project_id=project_id,
    )
    live_default_id = live_default.id
    deleted = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="deleted-default-candidate",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "deleted"},
        ),
        project_id=project_id,
    )
    deleted_id = deleted.id
    await svc.soft_delete(deleted_id, project_id=project_id)

    operations = (
        lambda: svc.update(
            deleted_id,
            UpdateCredentialRequest(name="must-not-change"),
            project_id=project_id,
        ),
        lambda: svc.set_default(deleted_id, project_id=project_id),
        lambda: svc.clear_default(deleted_id, project_id=project_id),
    )
    for operation in operations:
        with pytest.raises(AppError) as exc:
            await operation()
        assert exc.value.code == "CREDENTIAL_NOT_FOUND"
        assert (await svc.get(live_default_id, project_id=project_id)).is_default is True


@pytest.mark.asyncio
async def test_resource_lifecycle_commands_are_idempotent_and_clear_default(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="model",
            name="idempotent-model",
            provider="openai",
            protocol="openai",
            data={"API_KEY": "secret"},
            is_default=True,
        ),
        project_id=project_id,
    )

    first_archive = await svc.archive(cred.id, project_id=project_id)
    second_archive = await svc.archive(cred.id, project_id=project_id)
    assert first_archive.archived_at == second_archive.archived_at
    assert second_archive.is_default is False

    first_restore = await svc.restore(cred.id, project_id=project_id)
    second_restore = await svc.restore(cred.id, project_id=project_id)
    assert first_restore.archived_at is None
    assert second_restore.archived_at is None

    await svc.soft_delete(cred.id, project_id=project_id)
    await svc.soft_delete(cred.id, project_id=project_id)
    assert await svc.get(cred.id, project_id=project_id) is None


@pytest.mark.asyncio
async def test_legacy_disabled_mcp_oauth_cannot_restore(db_session, project_id):
    group = JoySafeterCredentialGroup(project_id=project_id, name="legacy-oauth-group")
    db_session.add(group)
    await db_session.flush()
    credential = JoySafeterCredential(
        project_id=project_id,
        kind="mcp",
        name="legacy-oauth-member",
        data={"token_value": "legacy"},
        mcp_server_url="https://legacy.example.com/mcp",
        normalized_mcp_server_url="https://legacy.example.com/mcp",
        credential_type="oauth",
        group_id=group.id,
    )
    db_session.add(credential)
    await db_session.commit()

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    await svc.archive(credential.id, project_id=project_id)
    with pytest.raises(AppError) as exc:
        await svc.restore(credential.id, project_id=project_id)
    assert exc.value.code == "CREDENTIAL_AUTH_SCHEME_DISABLED"


@pytest.mark.asyncio
async def test_list_filters_archived_before_pagination_and_keeps_default_compatibility(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    active = await svc.create(
        CreateCredentialRequest(kind="service", name="active-list-item", data={"TOKEN": "a"}),
        project_id=project_id,
    )
    archived = await svc.create(
        CreateCredentialRequest(kind="service", name="archived-list-item", data={"TOKEN": "b"}),
        project_id=project_id,
    )
    await svc.archive(archived.id, project_id=project_id)

    active_only, has_more = await svc.list(
        project_id=project_id,
        kind="service",
        include_archived=False,
        limit=1,
    )
    assert [credential.id for credential in active_only] == [active.id]
    assert has_more is False

    explicit_all, _ = await svc.list(
        project_id=project_id,
        kind="service",
        include_archived=True,
        limit=2,
    )
    assert {credential.id for credential in explicit_all} == {active.id, archived.id}

    compatible_default, _ = await svc.list(
        project_id=project_id,
        kind="service",
        limit=2,
    )
    assert {credential.id for credential in compatible_default} == {active.id, archived.id}


@pytest.mark.asyncio
async def test_recreate_soft_deleted_name_preserves_history(db_session, project_id):
    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    deleted = await svc.create(
        CreateCredentialRequest(kind="service", name="reusable", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    await svc.soft_delete(deleted.id, project_id=project_id)

    replacement = await svc.create(
        CreateCredentialRequest(kind="service", name="reusable", data={"TOKEN": "new"}),
        project_id=project_id,
    )

    rows = await db_session.execute(
        select(JoySafeterCredential).where(
            JoySafeterCredential.project_id == project_id,
            JoySafeterCredential.kind == "service",
            JoySafeterCredential.name == "reusable",
        )
    )
    credentials = list(rows.scalars().all())
    assert {credential.id for credential in credentials} == {deleted.id, replacement.id}
    assert next(credential for credential in credentials if credential.id == deleted.id).deleted_at is not None


@pytest.mark.asyncio
async def test_create_mcp_sets_normalized_url(db_session, project_id):
    group = JoySafeterCredentialGroup(project_id=project_id, name=f"grp-{uuid.uuid4()}")
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp1",
            mcp_server_url="HTTPS://Example.com:443/mcp/",
            group_id=group.id,
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )
    assert cred.kind == "mcp"
    assert cred.credential_type == "static_bearer"
    assert cred.mcp_server_url == "HTTPS://Example.com:443/mcp/"
    assert cred.normalized_mcp_server_url == "https://example.com/mcp"


@pytest.mark.asyncio
async def test_create_mcp_persists_header_api_key_scheme_and_material(db_session, project_id):
    group = JoySafeterCredentialGroup(project_id=project_id, name=f"grp-{uuid.uuid4()}")
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp-api-key",
            auth_scheme="header_api_key",
            mcp_server_url="https://example.com/mcp",
            group_id=group.id,
            data={"token_value": "secret", "header_name": "X-Corp-Key"},
        ),
        project_id=project_id,
    )

    assert cred.credential_type == "header_api_key"
    assert svc.get_credential_data(cred) == {
        "token_value": "secret",
        "header_name": "X-Corp-Key",
    }


@pytest.mark.asyncio
async def test_update_mcp_rejects_clearing_static_bearer_token(db_session, project_id):
    group = JoySafeterCredentialGroup(project_id=project_id, name=f"grp-{uuid.uuid4()}")
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp1",
            mcp_server_url="https://example.com/mcp",
            group_id=group.id,
            data={"token_value": "t"},
        ),
        project_id=project_id,
    )

    with pytest.raises(AppError) as exc:
        await svc.update(
            cred.id,
            UpdateCredentialRequest(data={"token_value": ""}),
            project_id=project_id,
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_update_mcp_rejects_explicit_auto_auth_scheme(db_session, project_id):
    group = JoySafeterCredentialGroup(project_id=project_id, name=f"grp-{uuid.uuid4()}")
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp-auto",
            mcp_server_url="https://example.com/mcp",
            group_id=group.id,
            data={"token_value": "secret"},
        ),
        project_id=project_id,
    )

    with pytest.raises(AppError) as exc:
        await svc.update(
            cred.id,
            UpdateCredentialRequest(auth_scheme="auto"),
            project_id=project_id,
        )

    assert exc.value.code == "CREDENTIAL_FIELD_INVALID"


@pytest.mark.asyncio
async def test_update_mcp_changes_auth_scheme_and_material_atomically(db_session, project_id):
    group = JoySafeterCredentialGroup(project_id=project_id, name=f"grp-{uuid.uuid4()}")
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)

    svc = CredentialService(db_session, audit_actor=CredentialAuditActor.system("test"))
    cred = await svc.create(
        CreateCredentialRequest(
            kind="mcp",
            name="mcp-switch-auth",
            mcp_server_url="https://example.com/mcp",
            group_id=group.id,
            data={"token_value": "old-secret"},
        ),
        project_id=project_id,
    )

    updated = await svc.update(
        cred.id,
        UpdateCredentialRequest(
            auth_scheme="custom_header",
            data={
                "token_value": "new-secret",
                "header_name": "X-Service-Authorization",
                "value_prefix": "Token ",
            },
        ),
        project_id=project_id,
    )

    assert updated.credential_type == "custom_header"
    assert svc.get_credential_data(updated) == {
        "token_value": "new-secret",
        "header_name": "X-Service-Authorization",
        "value_prefix": "Token ",
    }
