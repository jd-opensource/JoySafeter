"""Service-level tests for Task 9b: a webhook trigger authenticates the inbound
caller against a stable ``webhook_auth_credential_id`` FK + ``webhook_auth_field``
(was the name-based ``secret_ref`` / ``secret_key`` pair on the old SecretService).

Real-DB tests via conftest's ``db_session``: the FK to ``joysafeter_credentials``
and the CredentialService kind check are enforced against Postgres. The full app
is intentionally un-loadable mid-cutover, so everything here runs at the
service/model level (no TestClient).
"""

import ast
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_domain.services.joysafeter_trigger_config_policy import TriggerConfigPolicy
from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService
from app.joysafeter_domain.services.joysafeter_trigger_webhook_auth_service import WebhookAuthService
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.ids import CredentialId

_WEBHOOK_SECRET = "s3cr3t-webhook-material"


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


async def _make_service_credential(
    db_session, project_id: str, data: dict[str, str] | None = None
) -> CredentialId:
    cred = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="service",
            name=f"s-{uuid.uuid4()}",
            data=data if data is not None else {"WEBHOOK_SECRET": _WEBHOOK_SECRET},
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
            data={"API_KEY": "sk-x"},
        ),
        project_id=project_id,
    )
    return cred.id


async def _make_agent(db_session, project_id: str) -> JoySafeterAgent:
    agent = JoySafeterAgent(name=f"agent-{uuid.uuid4()}", project_id=project_id)
    db_session.add(agent)
    await db_session.commit()
    await db_session.refresh(agent)
    return agent


@pytest.mark.asyncio
async def test_resolve_reads_field_from_service_credential(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    svc = WebhookAuthService(db_session)

    value = await svc.resolve_secret_value(
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        project_id=project_id,
    )

    assert value == _WEBHOOK_SECRET


@pytest.mark.asyncio
async def test_hmac_verify_passes_with_resolved_secret(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    svc = WebhookAuthService(db_session)
    secret = await svc.resolve_secret_value(
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        project_id=project_id,
    )

    raw_body = b'{"event":"ping"}'
    signature = "sha256=" + WebhookAuthService.sign(secret, raw_body)

    assert WebhookAuthService.verify_with_secret(
        config={"auth_methods": ["hmac"]},
        raw_body=raw_body,
        secret=secret,
        signature=signature,
        token=None,
    )


@pytest.mark.asyncio
async def test_token_verify_passes_with_resolved_secret(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    svc = WebhookAuthService(db_session)
    secret = await svc.resolve_secret_value(
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        project_id=project_id,
    )

    assert WebhookAuthService.verify_with_secret(
        config={"auth_methods": ["token"]},
        raw_body=b"",
        secret=secret,
        signature=None,
        token=secret,
    )
    assert not WebhookAuthService.verify_with_secret(
        config={"auth_methods": ["token"]},
        raw_body=b"",
        secret=secret,
        signature=None,
        token="wrong",
    )


@pytest.mark.asyncio
async def test_missing_credential_raises_not_found(db_session, project_id):
    svc = WebhookAuthService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.resolve_secret_value(
            webhook_auth_credential_id=CredentialId.new(),
            webhook_auth_field="WEBHOOK_SECRET",
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_archived_credential_raises_not_found(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(cred_id, project_id=project_id)
    credential.archived_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await WebhookAuthService(db_session).resolve_secret_value(
            webhook_auth_credential_id=cred_id,
            webhook_auth_field="WEBHOOK_SECRET",
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_STATE_INVALID"


@pytest.mark.asyncio
async def test_non_service_credential_raises_kind_invalid(db_session, project_id):
    model_cred_id = await _make_model_credential(db_session, project_id)
    svc = WebhookAuthService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.resolve_secret_value(
            webhook_auth_credential_id=model_cred_id,
            webhook_auth_field="API_KEY",
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_KIND_INVALID"


@pytest.mark.asyncio
async def test_absent_field_raises_key_not_found(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id)
    svc = WebhookAuthService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.resolve_secret_value(
            webhook_auth_credential_id=cred_id,
            webhook_auth_field="NOPE",
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_blank_field_value_raises_value_blank(db_session, project_id):
    cred_id = await _make_service_credential(db_session, project_id, data={"WEBHOOK_SECRET": "   "})
    svc = WebhookAuthService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.resolve_secret_value(
            webhook_auth_credential_id=cred_id,
            webhook_auth_field="WEBHOOK_SECRET",
            project_id=project_id,
        )
    assert exc.value.code == "TRIGGER_SECRET_VALUE_BLANK"


@pytest.mark.asyncio
async def test_credential_from_other_project_raises_not_found(db_session, project_id):
    other_project = await _make_project(db_session)
    other_cred_id = await _make_service_credential(db_session, other_project)
    svc = WebhookAuthService(db_session)
    with pytest.raises(AppError) as exc:
        await svc.resolve_secret_value(
            webhook_auth_credential_id=other_cred_id,
            webhook_auth_field="WEBHOOK_SECRET",
            project_id=project_id,
        )
    assert exc.value.code == "CREDENTIAL_NOT_FOUND"


@pytest.mark.asyncio
async def test_deleted_credential_raises_canonical_not_found(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc:
        await WebhookAuthService(db_session).resolve_secret_value(
            webhook_auth_credential_id=credential_id,
            webhook_auth_field="WEBHOOK_SECRET",
            project_id=project_id,
            auth_methods=frozenset({"hmac"}),
        )

    assert exc.value.code == "CREDENTIAL_NOT_FOUND"
    assert exc.value.data == {"credential_id": str(credential_id)}


@pytest.mark.asyncio
async def test_resolve_authorizes_exact_webhook_method_and_field(db_session, project_id):
    credential_id = await _make_service_credential(
        db_session,
        project_id,
        data={"WEBHOOK_SECRET": _WEBHOOK_SECRET, "OTHER": "must-not-load"},
    )

    secret = await WebhookAuthService(db_session).resolve_secret_value(
        webhook_auth_credential_id=credential_id,
        webhook_auth_field="WEBHOOK_SECRET",
        project_id=project_id,
        auth_methods=frozenset({"hmac"}),
    )

    assert secret == _WEBHOOK_SECRET


@pytest.mark.asyncio
async def test_trigger_create_uses_canonical_webhook_binding_and_preserves_payload(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)

    trigger = await JoySafeterTriggerService(db_session).create(
        name=f"hook-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt_template="handle webhook",
        type="webhook",
        webhook_auth_credential_id=credential_id,
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
        project_id=project_id,
    )

    assert trigger.webhook_auth_credential_id == credential_id
    assert trigger.webhook_auth_field == "WEBHOOK_SECRET"
    assert trigger.config["auth_methods"] == ["hmac"]


@pytest.mark.asyncio
async def test_trigger_create_maps_invalid_auth_method_to_semantic_error(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)

    with pytest.raises(AppError) as exc:
        await JoySafeterTriggerService(db_session).create(
            name=f"hook-{uuid.uuid4()}",
            agent_id=agent.id,
            prompt_template="handle webhook",
            type="webhook",
            webhook_auth_credential_id=credential_id,
            webhook_auth_field="WEBHOOK_SECRET",
            auth_methods=["unsupported"],
            project_id=project_id,
        )

    assert exc.value.code == "TRIGGER_AUTH_METHODS_INVALID"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_methods",
    (
        [["hmac"]],
        [123],
    ),
    ids=("unhashable", "non-string"),
)
async def test_trigger_create_rejects_malformed_auth_method_collections(
    db_session,
    project_id,
    auth_methods,
):
    credential_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)

    with pytest.raises(AppError) as exc:
        await JoySafeterTriggerService(db_session).create(
            name=f"hook-{uuid.uuid4()}",
            agent_id=agent.id,
            prompt_template="handle webhook",
            type="webhook",
            webhook_auth_credential_id=credential_id,
            webhook_auth_field="WEBHOOK_SECRET",
            auth_methods=auth_methods,
            project_id=project_id,
        )

    assert exc.value.code == "TRIGGER_AUTH_METHODS_INVALID"


@pytest.mark.asyncio
async def test_trigger_update_maps_invalid_field_constructor_to_field_missing(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    service = JoySafeterTriggerService(db_session)
    trigger = await service.create(
        name=f"hook-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt_template="handle webhook",
        type="webhook",
        webhook_auth_credential_id=credential_id,
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
        project_id=project_id,
    )

    with pytest.raises(AppError) as exc:
        await service.update(
            trigger.id,
            project_id,
            webhook_auth_field="X" * 300,
        )

    assert exc.value.code == "CREDENTIAL_FIELD_MISSING"


@pytest.mark.asyncio
async def test_trigger_update_maps_invalid_method_to_semantic_error(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    service = JoySafeterTriggerService(db_session)
    trigger = await service.create(
        name=f"hook-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt_template="handle webhook",
        type="webhook",
        webhook_auth_credential_id=credential_id,
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
        project_id=project_id,
    )

    with pytest.raises(AppError) as exc:
        await service.update(trigger.id, project_id, auth_methods=["unsupported"])

    assert exc.value.code == "TRIGGER_AUTH_METHODS_INVALID"


@pytest.mark.asyncio
async def test_trigger_update_translates_non_iterable_auth_methods(db_session, project_id):
    credential_id = await _make_service_credential(db_session, project_id)
    agent = await _make_agent(db_session, project_id)
    service = JoySafeterTriggerService(db_session)
    trigger = await service.create(
        name=f"hook-{uuid.uuid4()}",
        agent_id=agent.id,
        prompt_template="handle webhook",
        type="webhook",
        webhook_auth_credential_id=credential_id,
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
        project_id=project_id,
    )

    with pytest.raises(AppError) as exc:
        await service.update(trigger.id, project_id, auth_methods=123)

    assert exc.value.code == "TRIGGER_AUTH_METHODS_INVALID"


# --- config policy: presence validation by id + field ---------------------------


def test_config_policy_requires_credential_id_for_webhook():
    with pytest.raises(AppError) as exc:
        TriggerConfigPolicy.validate_create_fields(
            type="webhook",
            session_mode="fresh",
            pinned_session_id=None,
            session_key=None,
            cron_expr=None,
            run_at=None,
            timezone_name="UTC",
            concurrency_policy="allow",
            webhook_auth_credential_id=None,
            webhook_auth_field="WEBHOOK_SECRET",
            auth_methods=["hmac"],
        )
    assert exc.value.code == "TRIGGER_SECRET_REQUIRED"


def test_config_policy_requires_field_for_webhook():
    with pytest.raises(AppError) as exc:
        TriggerConfigPolicy.validate_create_fields(
            type="webhook",
            session_mode="fresh",
            pinned_session_id=None,
            session_key=None,
            cron_expr=None,
            run_at=None,
            timezone_name="UTC",
            concurrency_policy="allow",
            webhook_auth_credential_id=CredentialId.new(),
            webhook_auth_field=None,
            auth_methods=["hmac"],
        )
    assert exc.value.code == "TRIGGER_SECRET_KEY_REQUIRED"


def test_config_policy_accepts_credential_id_and_field():
    # No raise: presence + auth_methods satisfied.
    TriggerConfigPolicy.validate_create_fields(
        type="webhook",
        session_mode="fresh",
        pinned_session_id=None,
        session_key=None,
        cron_expr=None,
        run_at=None,
        timezone_name="UTC",
        concurrency_policy="allow",
        webhook_auth_credential_id=CredentialId.new(),
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
    )


def test_build_config_serializes_credential_id_to_string():
    cred_id = CredentialId.new()
    config = TriggerConfigPolicy.build_config(
        type="webhook",
        webhook_auth_credential_id=cred_id,
        webhook_auth_field="WEBHOOK_SECRET",
        auth_methods=["hmac"],
        dedupe_header=None,
    )
    assert config["webhook_auth_credential_id"] == str(cred_id)
    assert config["webhook_auth_field"] == "WEBHOOK_SECRET"
    assert config["dedupe_header"] == "x-joysafeter-delivery"


def test_webhook_binding_uses_field_scoped_material_port_only() -> None:
    root = Path(__file__).resolve().parents[1] / "app/joysafeter_domain/services"
    source = "\n".join((root / name).read_text() for name in ("joysafeter_trigger_service.py", "joysafeter_trigger_webhook_auth_service.py"))
    assert "WebhookAuthBinding" in source
    assert "material_adapter.load" in source
    for forbidden in ("CredentialService", "credential.kind", "get_credential_data", "reveal_values", "LegacyV1MaterialProtector"):
        assert forbidden not in source


def test_webhook_binding_construction_is_inside_translation_boundary() -> None:
    path = Path(__file__).resolve().parents[1] / "app/joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    parents: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"WebhookAuthMethod", "CredentialFieldName", "WebhookAuthBinding"}
    ]
    assert calls
    for call in calls:
        parent = parents.get(call)
        while parent is not None and not isinstance(parent, ast.Try):
            parent = parents.get(parent)
        assert isinstance(parent, ast.Try), ast.unparse(call)
