from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from app.joysafeter_application.credentials.binding_service import (
    ModelInferenceResolution,
    ResolvedCredentialMaterial,
    ValidatedCredentialBinding,
)
from app.joysafeter_application.credentials.material_access_service import (
    CredentialMaterialAccessService,
)
from app.joysafeter_application.credentials.ports import (
    CredentialAccessAuditEntry,
    CredentialAccessContext,
    CredentialAccessResult,
    CredentialAuditActor,
)
from app.joysafeter_domain.credentials import (
    CredentialFieldName,
    CredentialId,
    EngineKind,
    ModelInferenceBinding,
    ProjectId,
    WebhookAuthBinding,
    WebhookAuthMethod,
)
from app.joysafeter_domain.credentials.policies import (
    CredentialPolicyError,
    CredentialPolicyErrorCode,
)
from app.joysafeter_shared.security.credential_cipher import CredentialCiphertextError


class _BindingService:
    def __init__(self, validated, *, error: Exception | None = None, resolution=None) -> None:
        self.validated = validated
        self.error = error
        self.resolution = resolution
        self.validate_calls = []
        self.model_calls = []

    async def validate(self, binding, *, catalog_context=None):
        self.validate_calls.append((binding, catalog_context))
        if self.error is not None:
            raise self.error
        return self.validated

    async def validate_model_inference(self, binding):
        self.model_calls.append(binding)
        if self.error is not None:
            raise self.error
        return self.validated, self.resolution


class _MaterialPort:
    def __init__(self, material=None, *, error: Exception | None = None) -> None:
        self.material = material
        self.error = error
        self.calls = []

    async def load(self, binding):
        self.calls.append(binding)
        if self.error is not None:
            raise self.error
        return self.material


class _AuditPort:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.entries = []
        self.error = error

    async def append(self, entry) -> bool:
        self.entries.append(entry)
        if self.error is not None:
            raise self.error
        return True


def _context() -> CredentialAccessContext:
    return CredentialAccessContext(
        consumer_type="webhook_trigger",
        consumer_id="trig_example",
        actor=CredentialAuditActor.system("webhook_ingress"),
    )


def _webhook_binding() -> tuple[WebhookAuthBinding, ValidatedCredentialBinding, CredentialFieldName]:
    field = CredentialFieldName("WEBHOOK_SECRET")
    binding = WebhookAuthBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("cred_00000000-0000-0000-0000-000000000001"),
        credential_field=field,
        methods=frozenset({WebhookAuthMethod.HMAC}),
    )
    return binding, ValidatedCredentialBinding(binding, frozenset({field})), field


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_material_access_records_success_without_secret_payload() -> None:
    binding, validated, field = _webhook_binding()
    material = ResolvedCredentialMaterial({field: "top-secret"})
    binding_service = _BindingService(validated)
    material_port = _MaterialPort(material)
    audit = _AuditPort()
    service = CredentialMaterialAccessService(binding_service, material_port, audit)

    resolved = await service.resolve(binding, context=_context())

    assert resolved is material
    assert material_port.calls == [validated]
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.result is CredentialAccessResult.SUCCESS
    assert entry.error_code is None
    assert entry.credential_kind == "service"
    assert entry.field_names == (field,)
    assert entry.actor.principal_id == "webhook_ingress"
    assert "top-secret" not in json.dumps(asdict(entry), default=str)


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_material_access_records_policy_denial_without_loading_material() -> None:
    binding, _validated, _field = _webhook_binding()
    binding_service = _BindingService(
        None,
        error=CredentialPolicyError(CredentialPolicyErrorCode.ARCHIVED, "credential is archived"),
    )
    material_port = _MaterialPort()
    audit = _AuditPort()
    service = CredentialMaterialAccessService(binding_service, material_port, audit)

    with pytest.raises(CredentialPolicyError):
        await service.resolve(binding, context=_context())

    assert material_port.calls == []
    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.result is CredentialAccessResult.DENIED
    assert entry.error_code == "policy_archived"
    assert entry.field_names == ()


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_material_access_records_ciphertext_failure_with_authorized_fields() -> None:
    binding, validated, field = _webhook_binding()
    audit = _AuditPort()
    service = CredentialMaterialAccessService(
        _BindingService(validated),
        _MaterialPort(error=CredentialCiphertextError("must not be recorded")),
        audit,
    )

    with pytest.raises(CredentialCiphertextError):
        await service.resolve(binding, context=_context())

    assert len(audit.entries) == 1
    entry = audit.entries[0]
    assert entry.result is CredentialAccessResult.FAILED
    assert entry.error_code == "ciphertext_invalid"
    assert entry.field_names == (field,)
    assert "must not be recorded" not in repr(entry)


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_material_access_fails_closed_when_success_audit_cannot_persist() -> None:
    binding, validated, field = _webhook_binding()
    service = CredentialMaterialAccessService(
        _BindingService(validated),
        _MaterialPort(ResolvedCredentialMaterial({field: "top-secret"})),
        _AuditPort(error=RuntimeError("audit unavailable")),
    )

    with pytest.raises(RuntimeError, match="audit unavailable"):
        await service.resolve(binding, context=_context())


@pytest.mark.no_db
@pytest.mark.asyncio
async def test_model_material_access_returns_resolution_and_audits_model_usage() -> None:
    field = CredentialFieldName("OPENAI_API_KEY")
    binding = ModelInferenceBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("cred_00000000-0000-0000-0000-000000000002"),
        engine_kind=EngineKind.CODEX,
        model_id="gpt-5",
    )
    validated = object.__new__(ValidatedCredentialBinding)
    object.__setattr__(validated, "binding", binding)
    object.__setattr__(validated, "authorized_fields", frozenset({field}))
    object.__setattr__(validated, "requests_all_fields", False)
    resolution = ModelInferenceResolution(
        provider_id="openai",
        protocol_id="openai_responses",
        credential_profile_id="openai",
        base_url_key="OPENAI_BASE_URL",
        model_key="OPENAI_MODEL",
        default_base_url="https://api.openai.com",
    )
    material = ResolvedCredentialMaterial({field: "top-secret"})
    audit = _AuditPort()
    service = CredentialMaterialAccessService(
        _BindingService(validated, resolution=resolution),
        _MaterialPort(material),
        audit,
    )

    resolved, resolved_policy = await service.resolve_model_inference(binding, context=_context())

    assert resolved is material
    assert resolved_policy is resolution
    assert audit.entries[0].credential_kind == "model"
    assert audit.entries[0].field_names == (field,)


@pytest.mark.no_db
def test_access_context_rejects_blank_consumer_type() -> None:
    with pytest.raises(ValueError, match="consumer type"):
        CredentialAccessContext(
            consumer_type="  ",
            actor=CredentialAuditActor.system("test"),
        )


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("result", "error_code"),
    (
        (CredentialAccessResult.SUCCESS, "unexpected_error"),
        (CredentialAccessResult.DENIED, None),
        (CredentialAccessResult.FAILED, "  "),
    ),
)
def test_access_audit_entry_rejects_inconsistent_result_and_error_code(result, error_code) -> None:
    binding, _validated, field = _webhook_binding()

    with pytest.raises(ValueError, match="error code"):
        CredentialAccessAuditEntry(
            project_id=binding.project_id,
            credential_id=binding.credential_id,
            credential_kind="service",
            usage=binding.usage,
            consumer_type="webhook_auth",
            actor=CredentialAuditActor.system("test"),
            field_names=(field,),
            result=result,
            error_code=error_code,
        )
