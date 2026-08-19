"""Service-level tests for Task 9c: an Environment references service credentials
by stable id (was name-based ``credential_ref``/``secret_refs``).

Real-DB tests via conftest's ``db_session``: the CredentialService kind check is
enforced against Postgres. The full app is intentionally un-loadable mid-cutover,
so everything here runs at the service/route-helper level (no TestClient).
"""

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select

from app.joysafeter_api.api.v1.environments import (
    _validate_secret_refs,
    create_environment,
    update_environment,
)
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_domain.credentials import CredentialUsage, DependencyDisposition
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.schemas.joysafeter_environment import (
    CreateEnvironmentRequest,
    EnvironmentConfig,
    EnvironmentSecretReference,
    UpdateEnvironmentRequest,
    extract_environment_secret_references,
)
from app.joysafeter_domain.services import (
    joysafeter_environment_service as environment_service_module,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_domain.services.joysafeter_environment_service import (
    EnvironmentService,
    _changed_credential_binding_usages,
)
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
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


async def _make_service_credential(db_session, project_id: str, data: dict[str, str] | None = None) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="service",
            name=f"s-{uuid.uuid4()}",
            data=data if data is not None else {"ACCESS_TOKEN": "t"},
        ),
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


def _auth_ctx(project_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


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
async def test_validate_rejects_archived_credential_with_state_invalid(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.archived_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, _egress_config(credential_id), project_id)

    assert exc.value.code == "CREDENTIAL_STATE_INVALID"
    assert exc.value.data == {
        "credential_id": str(credential_id),
        "source": "egress_services",
        "index": 0,
        "path": "egress_services[0]",
    }


@pytest.mark.asyncio
async def test_validate_rejects_deleted_credential_with_not_found(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, _egress_config(credential_id), project_id)

    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_http_egress_requires_exact_inject_field(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})

    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, _egress_config(credential_id), project_id)

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_environment_injection_requires_posix_material_names(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"NOT-POSIX": "value"})

    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(
            db_session,
            EnvironmentConfig(secret_refs=[str(credential_id)]),
            project_id,
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


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
        EnvironmentSecretReference(direct_id, "secret_refs", 0, "secret_refs[0]"),
        EnvironmentSecretReference(egress_id, "egress_services", 0, "egress_services[0]"),
    ]


def test_extract_environment_references_preserves_each_occurrence_and_path():
    credential_id = CredentialId.new()
    config = EnvironmentConfig(
        secret_refs=[credential_id],
        egress_services=[
            {
                "name": "one",
                "base_url": "https://one.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "ONE"},
            },
            {
                "name": "two",
                "base_url": "https://two.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "TWO"},
            },
        ],
    )

    assert extract_environment_secret_references(config) == [
        EnvironmentSecretReference(credential_id, "secret_refs", 0, "secret_refs[0]"),
        EnvironmentSecretReference(credential_id, "egress_services", 0, "egress_services[0]"),
        EnvironmentSecretReference(credential_id, "egress_services", 1, "egress_services[1]"),
    ]


@pytest.mark.asyncio
async def test_validate_same_credential_as_direct_and_egress_occurrences(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"ACCESS_TOKEN": "t"})
    config = EnvironmentConfig(
        secret_refs=[credential_id],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "ACCESS_TOKEN"},
            }
        ],
    )

    await _validate_secret_refs(db_session, config, project_id)


@pytest.mark.asyncio
async def test_validate_repeated_egress_credential_checks_each_field(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"VALID": "t"})
    config = EnvironmentConfig(
        egress_services=[
            {
                "name": "one",
                "base_url": "https://one.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "VALID"},
            },
            {
                "name": "two",
                "base_url": "https://two.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "MISSING"},
            },
        ]
    )

    with pytest.raises(AppError) as exc:
        await _validate_secret_refs(db_session, config, project_id)

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"
    assert exc.value.data == {
        "credential_id": str(credential_id),
        "source": "egress_services",
        "index": 1,
        "path": "egress_services[1]",
    }


@pytest.mark.asyncio
async def test_environment_create_route_accepts_same_credential_direct_and_egress(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"ACCESS_TOKEN": "t"})
    config = EnvironmentConfig(
        secret_refs=[credential_id],
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "ACCESS_TOKEN"},
            }
        ],
    )

    response = await create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=config),
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == config.model_dump(mode="json")


@pytest.mark.asyncio
async def test_environment_update_route_rejects_second_invalid_egress_occurrence(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id, data={"VALID": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    config = EnvironmentConfig(
        egress_services=[
            {
                "name": "one",
                "base_url": "https://one.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "VALID"},
            },
            {
                "name": "two",
                "base_url": "https://two.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "MISSING"},
            },
        ]
    )

    with pytest.raises(AppError) as exc:
        await update_environment(
            UpdateEnvironmentRequest(config=config),
            environment.id,
            db_session,
            _auth_ctx(project_id),
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"
    await db_session.refresh(environment)
    assert environment.config == EnvironmentConfig().model_dump(mode="json")


@pytest.mark.asyncio
async def test_environment_update_orders_mutation_audit_pending_single_commit_nudge(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    application = compose_credential_application(db_session, auto_commit=False)
    events: list[str] = []
    committed: list[None] = []
    impacts = []
    original_update = EnvironmentService.update_environment
    original_append = application.uow.audit.append
    original_mark = application.uow.impacts.mark_pending

    async def recorded_update(self, *args, **kwargs):
        events.append("mutation")
        return await original_update(self, *args, **kwargs)

    async def recorded_append(entry):
        events.append("audit")
        assert entry.target_type == "environment"
        await original_append(entry)

    async def recorded_mark(impact):
        events.append("pending")
        impacts.append(impact)
        return await original_mark(impact)

    async def recorded_nudge():
        events.append("nudge")

    monkeypatch.setattr(EnvironmentService, "update_environment", recorded_update)
    monkeypatch.setattr(
        environment_service_module, "compose_credential_application", lambda *args, **kwargs: application
    )
    monkeypatch.setattr(application.uow.audit, "append", recorded_append)
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)
    sqlalchemy_event.listen(
        db_session.sync_session,
        "after_commit",
        lambda session: (events.append("commit"), committed.append(None)),
    )

    config = EnvironmentConfig(secret_refs=[credential_id])
    response = await update_environment(
        UpdateEnvironmentRequest(config=config),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == config.model_dump(mode="json")
    assert events == ["mutation", "audit", "pending", "commit", "nudge"]
    assert len(committed) == 1
    assert [impact.usage for impact in impacts] == [CredentialUsage.ENVIRONMENT_INJECTION]
    assert impacts[0].dispositions == frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY})
    audit = (
        await db_session.execute(
            select(SecurityAuditLog).where(SecurityAuditLog.event_type == "environment.credentials.updated")
        )
    ).scalar_one()
    assert audit.details["target_type"] == "environment"


@pytest.mark.asyncio
async def test_environment_update_unchanged_binding_config_has_no_pending_impact(
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    config = EnvironmentConfig(secret_refs=[credential_id])
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=config),
        project_id=project_id,
    )
    application = compose_credential_application(db_session, auto_commit=False)
    marked = 0
    nudged = 0

    async def recorded_mark(impact):
        nonlocal marked
        marked += 1
        return impact

    async def recorded_nudge():
        nonlocal nudged
        nudged += 1

    monkeypatch.setattr(
        environment_service_module, "compose_credential_application", lambda *args, **kwargs: application
    )
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)

    response = await update_environment(
        UpdateEnvironmentRequest(config=config),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == config.model_dump(mode="json")
    assert marked == 0
    assert nudged == 0


def test_environment_binding_impact_usages_are_semantic_and_surface_specific() -> None:
    credential_id = CredentialId.new()
    direct = EnvironmentConfig(secret_refs=[credential_id]).model_dump(mode="json")
    egress = EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "TOKEN"},
            }
        ]
    ).model_dump(mode="json")
    both = EnvironmentConfig.model_validate({**egress, "secret_refs": [str(credential_id)]}).model_dump(mode="json")

    assert _changed_credential_binding_usages(direct, direct) == ()
    assert _changed_credential_binding_usages(None, direct) == (CredentialUsage.ENVIRONMENT_INJECTION,)
    assert _changed_credential_binding_usages(None, egress) == (CredentialUsage.HTTP_EGRESS,)
    assert set(_changed_credential_binding_usages(None, both)) == {
        CredentialUsage.ENVIRONMENT_INJECTION,
        CredentialUsage.HTTP_EGRESS,
    }


def test_environment_binding_impact_ignores_display_name_and_equivalent_url_spelling() -> None:
    credential_id = CredentialId.new()
    original = EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "TOKEN"},
            }
        ]
    ).model_dump(mode="json")
    renamed = EnvironmentConfig.model_validate(
        {
            **original,
            "egress_services": [{**original["egress_services"][0], "name": "customer-api"}],
        }
    ).model_dump(mode="json")
    equivalent_url = EnvironmentConfig.model_validate(
        {
            **original,
            "egress_services": [
                {
                    **original["egress_services"][0],
                    "base_url": "https://CRM.EXAMPLE.COM:443/api",
                }
            ],
        }
    ).model_dump(mode="json")

    assert _changed_credential_binding_usages(original, renamed) == ()
    assert _changed_credential_binding_usages(original, equivalent_url) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("new_name", "new_url"),
    (
        ("customer-api", "https://crm.example.com/api"),
        ("crm", "https://CRM.EXAMPLE.COM:443/api"),
    ),
    ids=("rename-only", "normalized-url-equivalent"),
)
async def test_environment_semantic_only_egress_changes_do_not_mark_or_nudge(
    db_session,
    project_id,
    monkeypatch,
    new_name,
    new_url,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    original = EnvironmentConfig(
        egress_services=[
            {
                "name": "crm",
                "base_url": "https://crm.example.com/api",
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "TOKEN"},
            }
        ]
    )
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}", config=original),
        project_id=project_id,
    )
    application = compose_credential_application(db_session, auto_commit=False)
    marked = 0
    nudged = 0

    async def recorded_mark(impact):
        nonlocal marked
        marked += 1
        return impact

    async def recorded_nudge():
        nonlocal nudged
        nudged += 1

    monkeypatch.setattr(
        environment_service_module, "compose_credential_application", lambda *args, **kwargs: application
    )
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)

    updated = EnvironmentConfig(
        egress_services=[
            {
                "name": new_name,
                "base_url": new_url,
                "service_credential_id": credential_id,
                "inject": {"type": "bearer", "secret_key": "TOKEN"},
            }
        ]
    )
    response = await update_environment(
        UpdateEnvironmentRequest(config=updated),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.config.model_dump(mode="json") == updated.model_dump(mode="json")
    assert marked == 0
    assert nudged == 0


@pytest.mark.asyncio
async def test_environment_update_nudge_failure_is_logged_and_nonfatal(
    db_session,
    project_id,
    monkeypatch,
    caplog,
):
    credential_id = await _make_service_credential(db_session, project_id, data={"TOKEN": "t"})
    environment = await EnvironmentService(db_session).create_environment(
        CreateEnvironmentRequest(name=f"env-{uuid.uuid4()}"),
        project_id=project_id,
    )
    application = compose_credential_application(db_session, auto_commit=False)

    async def failing_nudge():
        raise RuntimeError("relay unavailable")

    monkeypatch.setattr(
        environment_service_module, "compose_credential_application", lambda *args, **kwargs: application
    )
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", failing_nudge)

    response = await update_environment(
        UpdateEnvironmentRequest(config=EnvironmentConfig(secret_refs=[credential_id])),
        environment.id,
        db_session,
        _auth_ctx(project_id),
    )

    assert response.id == environment.id
    assert "environment credential impact nudge failed after commit" in caplog.text


def test_environment_binding_has_no_direct_credential_or_second_refresh_transaction() -> None:
    path = Path(__file__).resolve().parents[1] / "app/joysafeter_api/api/v1/environments.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    imported = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert {"EnvironmentInjectionBinding", "HttpEgressBinding"} <= imported
    assert "CredentialService" not in imported
    assert not {"kind", "get_credential_data", "reveal_values"} & attributes

    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"EnvironmentInjectionBinding", "HttpEgressBinding", "EgressInjectPolicy"}
    ]
    assert calls
    for call in calls:
        parent = parents.get(call)
        while parent is not None and not isinstance(parent, ast.Try):
            parent = parents.get(parent)
        assert isinstance(parent, ast.Try), ast.unparse(call)
