import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from pydantic import ValidationError
from sqlalchemy import inspect

from app.joysafeter_api.api.v1.agent_identity_capture import (
    _encrypt,
    environment_uses_agent_identity,
    prepare_agent_identity_capture,
    validate_agent_identity_configuration,
)
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_domain.models.joysafeter_task_identity import JoySafeterTaskIdentityContext
from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
from app.joysafeter_identity.config import (
    AgentIdentityProvider,
    resolve_agent_identity_provider,
)
from app.joysafeter_identity.service import cleanup_agent_identity
from app.joysafeter_shared.common.app_errors import ServiceUnavailableError
from app.joysafeter_shared.ids import AgentId, ProjectId, SessionId, TaskId, UserId
from app.joysafeter_shared.security.credential_cipher import CredentialCipher

pytestmark = pytest.mark.no_db
REPO_ROOT = Path(__file__).resolve().parents[2]
TEST_KEY_ID = "test-2026-08"
TEST_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def test_create_session_rejects_reserved_agent_identity_context_metadata() -> None:
    with pytest.raises(ValidationError, match="agent_identity_context"):
        CreateSessionRequest(
            agent_id=AgentId.new(),
            metadata={"agent_identity_context": {"user_name": "victim@example.com"}},
        )


def test_task_identity_context_is_task_scoped_and_cascades() -> None:
    table = inspect(JoySafeterTaskIdentityContext).local_table

    assert table.name == "joysafeter_task_identity_contexts"
    assert list(table.primary_key.columns.keys()) == ["task_id"]
    foreign_key = next(iter(table.c.task_id.foreign_keys))
    assert foreign_key.target_fullname == "joysafeter_tasks.id"
    assert foreign_key.ondelete == "CASCADE"
    assert table.c.encrypted_credential.nullable is True
    assert table.c.credential_fingerprint.nullable is True
    assert any(index.name == "uq_task_identity_auth_code_fingerprint" and index.unique for index in table.indexes)
    assert table.c.expires_at.nullable is False
    assert table.c.consumed_at.nullable is True


def test_identity_encryption_uses_versioned_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING", json.dumps({TEST_KEY_ID: TEST_KEY}))
    monkeypatch.setenv("JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID", TEST_KEY_ID)
    encrypted = _encrypt(
        "credential",
        TEST_KEY,
    )

    assert encrypted.startswith(f"enc:v2:{TEST_KEY_ID}:")
    assert "credential" not in encrypted


def test_identity_encryption_delegates_to_shared_cipher(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_encrypt(self: CredentialCipher, value: str) -> str:
        calls.append(value)
        return "enc:v1:shared"

    monkeypatch.setattr(CredentialCipher, "encrypt", fake_encrypt)

    assert (
        _encrypt(
            "credential",
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )
        == "enc:v1:shared"
    )
    assert calls == ["credential"]


@pytest.mark.parametrize("key", ["", "not-a-key", "00"])
def test_identity_encryption_rejects_invalid_keys(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING", raising=False)
    monkeypatch.delenv("JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID", raising=False)
    with pytest.raises(ValueError, match="32-byte"):
        _encrypt("credential", key)


def test_legacy_switch_does_not_select_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_switch = "AGENT_IDENTITY_" + "ENABLED"
    monkeypatch.delenv("AGENT_IDENTITY_PROVIDER", raising=False)
    monkeypatch.setenv(legacy_switch, "true")
    monkeypatch.setenv("AGENT_IDENTITY_BASE_URL", "https://identity.example.com")

    assert resolve_agent_identity_provider() is AgentIdentityProvider.NONE


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        (None, AgentIdentityProvider.NONE),
        ("", AgentIdentityProvider.NONE),
        ("none", AgentIdentityProvider.NONE),
        ("jd", AgentIdentityProvider.JD),
        (" JD ", AgentIdentityProvider.JD),
    ],
)
def test_identity_provider_selection_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
    provider: str | None,
    expected: AgentIdentityProvider,
) -> None:
    if provider is None:
        monkeypatch.delenv("AGENT_IDENTITY_PROVIDER", raising=False)
    else:
        monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", provider)

    assert resolve_agent_identity_provider() is expected


def test_invalid_identity_provider_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="AGENT_IDENTITY_PROVIDER"):
        resolve_agent_identity_provider()


def test_legacy_identity_switch_is_absent_from_runtime_and_deployment() -> None:
    legacy_switch = "AGENT_IDENTITY_" + "ENABLED"
    inspected_paths = [
        REPO_ROOT / "backend/app",
        REPO_ROOT / "backend/env.example",
        REPO_ROOT / "deploy",
    ]
    legacy_references = []
    for path in inspected_paths:
        files = path.rglob("*") if path.is_dir() else [path]
        for file_path in files:
            if not file_path.is_file():
                continue
            if {"target", "__pycache__"} & set(file_path.parts):
                continue
            if legacy_switch in file_path.read_text(errors="ignore"):
                legacy_references.append(file_path.relative_to(REPO_ROOT).as_posix())

    assert legacy_references == []


def test_disabled_identity_ignores_stale_jd_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "none")
    monkeypatch.delenv("AGENT_IDENTITY_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_IDENTITY_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("JOYSAFETER_VAULT_ENCRYPTION_KEY", raising=False)

    validate_agent_identity_configuration()


@pytest.mark.asyncio
async def test_disabled_identity_cleanup_has_no_jd_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "none")
    jd_cleanup = AsyncMock()
    monkeypatch.setattr(
        "app.joysafeter_identity.providers.jd.cleanup_agent_identity",
        jd_cleanup,
    )

    await cleanup_agent_identity(AgentId.new())

    jd_cleanup.assert_not_awaited()


def test_enabled_identity_requires_complete_api_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "jd")
    monkeypatch.delenv("AGENT_IDENTITY_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_IDENTITY_ALLOWED_HOSTS", raising=False)

    with pytest.raises(RuntimeError, match="AGENT_IDENTITY_BASE_URL"):
        validate_agent_identity_configuration()


@pytest.mark.asyncio
async def test_prepared_identity_capture_persists_task_scoped_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "jd")
    monkeypatch.setenv(
        "JOYSAFETER_VAULT_ENCRYPTION_KEY",
        TEST_KEY,
    )
    monkeypatch.setenv("JOYSAFETER_CREDENTIAL_ENCRYPTION_KEYRING", json.dumps({TEST_KEY_ID: TEST_KEY}))
    monkeypatch.setenv("JOYSAFETER_CREDENTIAL_ENCRYPTION_WRITE_KEY_ID", TEST_KEY_ID)
    monkeypatch.setenv("AGENT_IDENTITY_CONTEXT_TTL_SECONDS", "300")
    result = SimpleNamespace(scalar_one_or_none=lambda: "user@example.com")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=result),
        add=MagicMock(),
        commit=AsyncMock(),
    )
    request = SimpleNamespace(
        cookies={"identity": "browser-token", "unrelated": "must-not-be-stored"},
        headers={
            "cookie": "identity=browser-token; unrelated=must-not-be-stored",
            "user-agent": "browser-agent",
            "x-forwarded-for": "10.0.0.8",
            "authorization": "Bearer platform-session",
            "x-arbitrary-secret": "must-not-be-stored",
        },
    )
    agent = SimpleNamespace(metadata_={})
    user_id = UserId.new()
    project_id = ProjectId.new()
    auth_ctx = SimpleNamespace(user_id=user_id, project_id=project_id)
    monkeypatch.setenv("AGENT_IDENTITY_COOKIE_NAME", "identity")

    environment = {
        "config": {
            "egress_services": [
                {
                    "auth_source": "agent_identity",
                    "base_url": "https://crm.example.com/api/",
                }
            ]
        }
    }
    hook = await prepare_agent_identity_capture(db, request, auth_ctx, agent, environment)
    assert hook is not None
    task = SimpleNamespace(id=TaskId.new(), project_id=project_id)
    await hook(task)

    context = db.add.call_args.args[0]
    assert isinstance(context, JoySafeterTaskIdentityContext)
    assert context.task_id == task.id
    assert type(context.project_id) is ProjectId
    assert context.project_id == project_id
    assert type(context.user_id) is UserId
    assert context.user_id == user_id
    assert context.user_name == "user@example.com"
    assert context.credential_kind == "identity_token"
    assert context.credential_fingerprint is None
    assert context.encrypted_credential.startswith(f"enc:v2:{TEST_KEY_ID}:")
    protected = json.loads(
        CredentialCipher(
            TEST_KEY,
            keyring_json=json.dumps({TEST_KEY_ID: TEST_KEY}),
            write_key_id=TEST_KEY_ID,
        ).decrypt_stored(context.encrypted_credential)
    )
    assert protected == {
        "headers_map": {
            "Cookie": "identity=browser-token",
            "User-Agent": "browser-agent",
            "X-Forwarded-For": "10.0.0.8",
        },
        "identity_token": "browser-token",
        "version": 1,
    }
    assert int((context.expires_at - context.captured_at).total_seconds()) == 300
    db.commit.assert_awaited_once()


@pytest.mark.parametrize(
    "environment",
    [
        None,
        {"config": {}},
        {"config": {"egress_services": []}},
        {"config": {"egress_services": [{"auth_source": "service_credential"}]}},
    ],
)
def test_environment_without_agent_identity_does_not_request_capture(environment: object) -> None:
    assert environment_uses_agent_identity(environment) is False


def test_environment_with_agent_identity_requests_capture() -> None:
    assert environment_uses_agent_identity({"config": {"egress_services": [{"auth_source": "agent_identity"}]}}) is True


@pytest.mark.asyncio
async def test_static_credential_environment_does_not_store_identity_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_IDENTITY_PROVIDER", "jd")
    monkeypatch.setenv("AGENT_IDENTITY_COOKIE_NAME", "identity")
    db = SimpleNamespace(execute=AsyncMock(), add=MagicMock(), commit=AsyncMock())
    request = SimpleNamespace(
        cookies={"identity": "browser-token"},
        headers={"cookie": "identity=browser-token"},
    )

    hook = await prepare_agent_identity_capture(
        db,
        request,
        SimpleNamespace(user_id=UserId.new(), project_id=ProjectId.new()),
        SimpleNamespace(metadata_={}),
        {"config": {"egress_services": [{"auth_source": "service_credential"}]}},
    )

    assert hook is None
    db.execute.assert_not_awaited()
    db.add.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_submission_runs_identity_hook_before_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    task = JoySafeterTask(
        id=TaskId.new(),
        agent_id=AgentId.new(),
        chat_session_id=SessionId.new(),
        prompt="run",
        status="pending",
    )
    task_service = SimpleNamespace(
        get_by_idempotency_key=AsyncMock(return_value=None),
        create_task=AsyncMock(return_value=task),
        update_task_error=AsyncMock(),
    )
    session_svc = SimpleNamespace(
        update_session_status_for_task_event=AsyncMock(
            side_effect=lambda *args, **kwargs: order.append("session") or True
        ),
        send_event=AsyncMock(),
    )

    async def hook(created_task: JoySafeterTask) -> None:
        assert created_task is task
        order.append("identity")

    async def enqueue(task_id: TaskId) -> None:
        assert task_id == task.id
        order.append("enqueue")

    monkeypatch.setattr(
        "app.joysafeter_domain.services.task_submission_service.enqueue_joysafeter_task",
        enqueue,
    )
    service = TaskSubmissionService(AsyncMock())
    service.tasks = task_service

    await service.create_and_dispatch(
        agent_id=task.agent_id,
        prompt=task.prompt,
        system_prompt=None,
        chat_session_id=task.chat_session_id,
        session_svc=session_svc,
        timeout_sec=60,
        max_retries=0,
        project_id="project-1",
        user_id="user-1",
        org_id="org-1",
        idempotency_key=None,
        enforce_admission=False,
        before_enqueue=hook,
    )

    assert order == ["identity", "session", "enqueue"]


@pytest.mark.asyncio
async def test_idempotent_replay_does_not_rerun_identity_hook() -> None:
    task = JoySafeterTask(
        id=TaskId.new(),
        agent_id=AgentId.new(),
        chat_session_id=SessionId.new(),
        prompt="run",
        status="pending",
    )
    task_service = SimpleNamespace(get_by_idempotency_key=AsyncMock(return_value=task))
    session_svc = SimpleNamespace()
    hook = AsyncMock()
    service = TaskSubmissionService(AsyncMock())
    service.tasks = task_service

    returned, created = await service.create_and_dispatch(
        agent_id=task.agent_id,
        prompt=task.prompt,
        system_prompt=None,
        chat_session_id=task.chat_session_id,
        session_svc=session_svc,
        timeout_sec=60,
        max_retries=0,
        project_id="project-1",
        user_id="user-1",
        org_id="org-1",
        idempotency_key="same-request",
        enforce_admission=False,
        before_enqueue=hook,
    )

    assert returned is task
    assert created is False
    hook.assert_not_awaited()


@pytest.mark.asyncio
async def test_pre_enqueue_failure_rolls_back_before_task_compensation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    task = JoySafeterTask(
        id=TaskId.new(),
        agent_id=AgentId.new(),
        chat_session_id=SessionId.new(),
        prompt="run",
        status="pending",
    )
    db = SimpleNamespace(rollback=AsyncMock(side_effect=lambda: order.append("rollback")))
    task_service = SimpleNamespace(
        get_by_idempotency_key=AsyncMock(return_value=None),
        create_task=AsyncMock(return_value=task),
        update_task_error=AsyncMock(side_effect=lambda *args: order.append("task_failed")),
    )
    session_svc = SimpleNamespace(
        update_session_status_for_task_event=AsyncMock(return_value=False),
        send_event=AsyncMock(),
    )

    async def failing_hook(_: JoySafeterTask) -> None:
        raise RuntimeError("identity insert failed")

    service = TaskSubmissionService(db)
    service.tasks = task_service

    with pytest.raises(ServiceUnavailableError):
        await service.create_and_dispatch(
            agent_id=task.agent_id,
            prompt=task.prompt,
            system_prompt=None,
            chat_session_id=task.chat_session_id,
            session_svc=session_svc,
            timeout_sec=60,
            max_retries=0,
            project_id="project-1",
            user_id="user-1",
            org_id="org-1",
            idempotency_key=None,
            enforce_admission=False,
            before_enqueue=failing_hook,
        )

    assert order[:2] == ["rollback", "task_failed"]


def test_preprod_orchestrator_build_and_env_wire_identity_feature() -> None:
    dockerfile = (REPO_ROOT / "deploy/docker/orchestrator-rs.Dockerfile").read_text()
    compose = (REPO_ROOT / "deploy/docker-compose.yml").read_text()
    env_examples = [
        (REPO_ROOT / "backend/env.example").read_text(),
        (REPO_ROOT / "deploy/.env.example").read_text(),
        (REPO_ROOT / "deploy/.env.remote.example").read_text(),
    ]

    assert "cargo build --release --features jd-identity" in dockerfile
    assert "AGENT_IDENTITY_PROVIDER: ${AGENT_IDENTITY_PROVIDER:-none}" in compose
    for variable in (
        "AGENT_IDENTITY_PROVIDER",
        "AGENT_IDENTITY_BASE_URL",
        "AGENT_IDENTITY_ALLOWED_HOSTS",
        "AGENT_IDENTITY_COOKIE_NAME",
        "AGENT_IDENTITY_CONTEXT_TTL_SECONDS",
    ):
        assert variable in compose
        assert all(variable in env_example for env_example in env_examples)


def test_preprod_helm_identity_values_do_not_capture_orchestrator_settings() -> None:
    configmap = (REPO_ROOT / "deploy/helm/joysafeter-orchestrator/templates/configmap.yaml").read_text()
    base_values = yaml.safe_load((REPO_ROOT / "deploy/helm/joysafeter-orchestrator/values.yaml").read_text())
    values = yaml.safe_load((REPO_ROOT / "deploy/helm/joysafeter-orchestrator/values-pre.yaml").read_text())

    assert base_values["agentIdentity"]["provider"] == "none"
    assert values["agentIdentity"]["provider"] == "none"
    assert "agentIdentity.provider must be one of: none, jd" in configmap
    assert values["orchestrator"]["sandbox"]["idleTimeout"] == 120
    assert values["orchestrator"]["pool"]["minSize"] == 2
    assert values["orchestrator"]["logLevel"] == "debug"
    assert set(values["agentIdentity"]) <= {
        "provider",
        "baseUrl",
        "allowedHosts",
        "cookieName",
        "contextTtlSeconds",
        "clientId",
        "platformId",
        "authType",
        "identityType",
        "agentScene",
        "clientSecret",
    }
