from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

import app.joysafeter_domain.credentials as credential_domain_api
from app.joysafeter_domain.credentials import material as credential_material_module
from app.joysafeter_domain.credentials.bindings import (
    EgressInjectKind,
    EgressInjectPolicy,
    EngineKind,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ModelCatalogContext,
    ModelInferenceBinding,
    WebhookAuthBinding,
    WebhookAuthMethod,
)
from app.joysafeter_domain.credentials.dependencies import (
    CredentialDependency,
    CredentialImpact,
    DependencyDisposition,
    ReferenceSurfaceDescriptor,
    ReferenceSurfaceKind,
    ReferenceTarget,
)
from app.joysafeter_domain.credentials.lifecycle import (
    CredentialLifecycleCommand,
    CredentialLifecycleError,
    decide_credential_lifecycle,
    decide_group_lifecycle,
)
from app.joysafeter_domain.credentials.material import (
    CREDENTIAL_MATERIAL_MAX_FIELD_NAME_LENGTH,
    CREDENTIAL_MATERIAL_MAX_FIELDS,
    CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH,
    CredentialMaterial,
    SensitiveValue,
)
from app.joysafeter_domain.credentials.policies import (
    CredentialGroupRestoreContext,
    CredentialPolicyError,
    validate_credential_binding,
    validate_mcp_group_binding,
)
from app.joysafeter_domain.credentials.references import (
    CredentialReference,
    CredentialReferenceKind,
)
from app.joysafeter_domain.credentials.resource import (
    CredentialGroupResource,
    CredentialMaterialDescriptor,
    CredentialResource,
    McpCredentialIdentity,
    ModelCredentialIdentity,
    ServiceCredentialIdentity,
)
from app.joysafeter_domain.credentials.types import (
    CredentialAuthScheme,
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    CredentialKind,
    CredentialState,
    CredentialUsage,
    NormalizedEndpoint,
    NormalizedMcpUrl,
    canonicalize_auth_scheme,
    make_project_id,
)
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest

pytestmark = pytest.mark.no_db

BACKEND_ROOT = Path(__file__).resolve().parent.parent
CONTRACT_PATH = BACKEND_ROOT / "contracts" / "credential_domain_contract.json"


def _project(value: str = "project-a"):
    return make_project_id(value)


def _field(value: str = "API_KEY") -> CredentialFieldName:
    return CredentialFieldName(value)


def _descriptor(*names: str) -> CredentialMaterialDescriptor:
    return CredentialMaterialDescriptor(frozenset(_field(name) for name in names))


def _model_resource(
    *,
    state: CredentialState = CredentialState.ACTIVE,
    is_default: bool | None = None,
) -> CredentialResource:
    return CredentialResource(
        id=CredentialId("cred-model"),
        project_id=_project(),
        name="Model credential",
        kind=CredentialKind.MODEL,
        identity=ModelCredentialIdentity(provider_id="openai", protocol_id="responses"),
        material=_descriptor("API_KEY"),
        state=state,
        is_default=state is CredentialState.ACTIVE if is_default is None else is_default,
    )


def _service_resource(*, state: CredentialState = CredentialState.ACTIVE) -> CredentialResource:
    return CredentialResource(
        id=CredentialId("cred-service"),
        project_id=_project(),
        name="Service credential",
        kind=CredentialKind.SERVICE,
        identity=ServiceCredentialIdentity(auth_scheme=CredentialAuthScheme.STATIC_BEARER),
        material=_descriptor("API_KEY", "WEBHOOK_SECRET"),
        state=state,
        is_default=False,
    )


def _mcp_resource(
    *,
    state: CredentialState = CredentialState.ACTIVE,
    scheme: CredentialAuthScheme = CredentialAuthScheme.STATIC_BEARER,
    project_id: str = "project-a",
    group_id: str = "group-a",
    server_url: str = "https://mcp.example.com/api",
    fields: tuple[str, ...] = ("token_value",),
) -> CredentialResource:
    return CredentialResource(
        id=CredentialId("cred-mcp"),
        project_id=_project(project_id),
        name="MCP credential",
        kind=CredentialKind.MCP,
        identity=McpCredentialIdentity(
            group_id=CredentialGroupId(group_id),
            server_url=NormalizedMcpUrl(server_url),
            auth_scheme=scheme,
        ),
        material=_descriptor(*fields),
        state=state,
        is_default=False,
    )


def _catalog_context(
    *,
    provider_id: str = "openai",
    protocol_id: str = "responses",
    engine_kind: EngineKind = EngineKind.CODEX,
    model_ids: frozenset[str] | None = frozenset({"gpt-5"}),
) -> ModelCatalogContext:
    return ModelCatalogContext(
        provider_id=provider_id,
        protocol_id=protocol_id,
        engine_kind=engine_kind,
        model_ids=model_ids,
    )


def _group_restore_context(
    *,
    project_id: str = "project-a",
    members: tuple[CredentialResource, ...] | None = None,
    occupied_server_urls: frozenset[NormalizedMcpUrl] = frozenset(),
) -> CredentialGroupRestoreContext:
    return CredentialGroupRestoreContext(
        project_id=_project(project_id),
        members=members if members is not None else (_mcp_resource(),),
        occupied_server_urls=occupied_server_urls,
    )


def test_domain_enums_match_the_shared_machine_contract() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    assert [kind.value for kind in CredentialKind] == contract["credential_kinds"]
    assert [CredentialAuthScheme.STATIC_BEARER.value] == contract["auth_schemes"]
    assert contract["auth_scheme_aliases"] == {"bearer": "static_bearer"}
    assert contract["disabled_auth_schemes"] == ["oauth", "mcp_oauth"]
    assert {state.value for state in CredentialState} == {"active", "archived", "deleted"}
    assert {usage.value for usage in CredentialUsage} == {
        "model_inference",
        "webhook_auth",
        "environment_injection",
        "http_egress",
        "mcp_egress",
    }


def test_project_id_is_trimmed_and_non_empty() -> None:
    assert _project("  project-a  ") == "project-a"
    with pytest.raises(ValueError):
        _project("   ")
    with pytest.raises(TypeError):
        make_project_id(None)  # type: ignore[arg-type]


def test_auth_scheme_aliases_canonicalize_and_unknown_values_fail_closed() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    for scheme in contract["auth_schemes"]:
        assert canonicalize_auth_scheme(scheme).value == scheme
    for alias, canonical in contract["auth_scheme_aliases"].items():
        assert canonicalize_auth_scheme(alias).value == canonical
    for disabled in contract["disabled_auth_schemes"]:
        assert canonicalize_auth_scheme(disabled) is CredentialAuthScheme.OAUTH2_LEGACY_DISABLED

    assert (
        canonicalize_auth_scheme(CredentialAuthScheme.OAUTH2_LEGACY_DISABLED)
        is CredentialAuthScheme.OAUTH2_LEGACY_DISABLED
    )
    listed_values = {
        *contract["auth_schemes"],
        *contract["auth_scheme_aliases"],
        *contract["disabled_auth_schemes"],
    }
    invalid_values = {
        CredentialAuthScheme.OAUTH2_LEGACY_DISABLED.value,
        "surprise",
        *(value.upper() for value in listed_values),
        *(f" {value}" for value in listed_values),
        *(f"{value} " for value in listed_values),
    }
    for invalid in invalid_values - listed_values:
        with pytest.raises(ValueError, match="unsupported credential auth scheme"):
            canonicalize_auth_scheme(invalid)


def test_sensitive_value_never_reveals_in_repr_or_str() -> None:
    value = SensitiveValue("sk-never-print")
    assert "sk-never-print" not in repr(value)
    assert "sk-never-print" not in str(value)
    assert "issue_material_reveal_capability" not in credential_domain_api.__all__
    assert not hasattr(credential_domain_api, "issue_material_reveal_capability")
    assert value.reveal(credential_material_module._issue_material_reveal_capability()) == "sk-never-print"


def test_material_copies_input_mapping_and_is_immutable() -> None:
    raw = {_field(): SensitiveValue("x")}
    material = CredentialMaterial(raw)
    raw.clear()

    assert material.field_names == frozenset({_field()})
    assert "x" not in repr(material)
    with pytest.raises(TypeError):
        material.fields[_field("OTHER")] = SensitiveValue("y")  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        material.fields = {}  # type: ignore[misc]


@pytest.mark.parametrize(
    ("raw", "expected_error"),
    [
        ({_field(str(index)): SensitiveValue("x") for index in range(CREDENTIAL_MATERIAL_MAX_FIELDS + 1)}, "at most"),
        ({"": SensitiveValue("x")}, "field name"),
        ({"x" * (CREDENTIAL_MATERIAL_MAX_FIELD_NAME_LENGTH + 1): SensitiveValue("x")}, "field name"),
        ({"API_KEY": "plaintext"}, "SensitiveValue"),
        ({"API_KEY": {"nested": "value"}}, "SensitiveValue"),
    ],
)
def test_material_enforces_flat_field_limits(raw: object, expected_error: str) -> None:
    with pytest.raises((TypeError, ValueError), match=expected_error):
        CredentialMaterial(raw)  # type: ignore[arg-type]


def test_material_enforces_unicode_character_limits_and_posix_environment_names() -> None:
    CredentialFieldName("密" * CREDENTIAL_MATERIAL_MAX_FIELD_NAME_LENGTH)
    SensitiveValue("密" * CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH)
    with pytest.raises(ValueError, match="value"):
        SensitiveValue("密" * (CREDENTIAL_MATERIAL_MAX_VALUE_LENGTH + 1))

    material = CredentialMaterial(
        {
            CredentialFieldName("VALID_NAME_2"): SensitiveValue("x"),
            CredentialFieldName("NOT-POSIX"): SensitiveValue("y"),
        }
    )
    with pytest.raises(ValueError, match="POSIX"):
        material.validate_environment_field_names()


def test_resource_carries_only_a_material_descriptor() -> None:
    resource = _model_resource()
    assert resource.material.field_names == frozenset({_field("API_KEY")})
    assert not hasattr(resource.material, "fields")


def test_material_descriptor_enforces_the_same_field_count_limit() -> None:
    with pytest.raises(ValueError, match="at most"):
        CredentialMaterialDescriptor(
            frozenset(_field(str(index)) for index in range(CREDENTIAL_MATERIAL_MAX_FIELDS + 1))
        )


def test_inactive_model_resources_cannot_retain_default() -> None:
    for state in (CredentialState.ARCHIVED, CredentialState.DELETED):
        with pytest.raises(ValueError, match="inactive"):
            _model_resource(state=state, is_default=True)


def test_binding_union_carries_usage_specific_context() -> None:
    model = ModelInferenceBinding(
        project_id=_project(),
        credential_id=CredentialId("cred-model"),
        engine_kind=EngineKind.NATIVE,
        model_id="gpt-5",
    )
    webhook = WebhookAuthBinding(
        project_id=_project(),
        credential_id=CredentialId("cred-service"),
        credential_field=_field("WEBHOOK_SECRET"),
        methods=frozenset({WebhookAuthMethod.HMAC}),
    )
    environment = EnvironmentInjectionBinding(
        project_id=_project(),
        credential_id=CredentialId("cred-service"),
    )
    http = HttpEgressBinding(
        project_id=_project(),
        credential_id=CredentialId("cred-service"),
        endpoint=NormalizedEndpoint("https://api.example.com/v1"),
        inject=EgressInjectPolicy(
            kind=EgressInjectKind.API_KEY,
            credential_field=_field("API_KEY"),
            header="X-API-Key",
        ),
    )
    mcp = McpGroupBinding(
        project_id=_project(),
        group_ids=(CredentialGroupId("group-a"),),
        declared_server_urls=(NormalizedMcpUrl("https://declared.example.com/mcp"),),
    )

    assert model.usage is CredentialUsage.MODEL_INFERENCE
    assert model.engine_kind is EngineKind.NATIVE
    assert model.model_id == "gpt-5"
    assert webhook.usage is CredentialUsage.WEBHOOK_AUTH
    assert webhook.methods == frozenset({WebhookAuthMethod.HMAC})
    assert environment.usage is CredentialUsage.ENVIRONMENT_INJECTION
    assert http.usage is CredentialUsage.HTTP_EGRESS
    assert http.endpoint == "https://api.example.com/v1"
    assert mcp.usage is CredentialUsage.MCP_EGRESS


def test_binding_policy_accepts_valid_model_webhook_environment_and_http_bindings() -> None:
    validate_credential_binding(
        _model_resource(),
        ModelInferenceBinding(
            project_id=_project(),
            credential_id=CredentialId("cred-model"),
            engine_kind=EngineKind.CODEX,
            model_id="gpt-5",
        ),
        catalog_context=_catalog_context(),
    )


def test_model_binding_requires_matching_pure_catalog_context() -> None:
    binding = ModelInferenceBinding(
        project_id=_project(),
        credential_id=CredentialId("cred-model"),
        engine_kind=EngineKind.CODEX,
        model_id="gpt-5",
    )

    validate_credential_binding(_model_resource(), binding, catalog_context=_catalog_context())
    with pytest.raises(CredentialPolicyError, match="Catalog context is required"):
        validate_credential_binding(_model_resource(), binding)

    mismatches = (
        _catalog_context(provider_id="anthropic"),
        _catalog_context(protocol_id="chat_completions"),
        _catalog_context(engine_kind=EngineKind.NATIVE),
        _catalog_context(model_ids=frozenset({"other-model"})),
    )
    for context in mismatches:
        with pytest.raises(CredentialPolicyError, match="Catalog"):
            validate_credential_binding(_model_resource(), binding, catalog_context=context)


def test_model_catalog_context_rejects_invalid_model_id_containers_before_freezing() -> None:
    with pytest.raises(TypeError, match="non-string iterable"):
        _catalog_context(model_ids="gpt-5")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="strings"):
        _catalog_context(model_ids=["gpt-5", 7])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="blanks"):
        _catalog_context(model_ids=["gpt-5", " "])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="non-string iterable"):
        _catalog_context(model_ids=42)  # type: ignore[arg-type]

    context = _catalog_context(model_ids=[" gpt-5 ", "gpt-5-mini"])  # type: ignore[arg-type]
    assert context.model_ids == frozenset({"gpt-5", "gpt-5-mini"})
    validate_credential_binding(
        _service_resource(),
        WebhookAuthBinding(
            project_id=_project(),
            credential_id=CredentialId("cred-service"),
            credential_field=_field("WEBHOOK_SECRET"),
            methods=frozenset({WebhookAuthMethod.HMAC, WebhookAuthMethod.BEARER}),
        ),
    )
    validate_credential_binding(
        _service_resource(),
        EnvironmentInjectionBinding(
            project_id=_project(),
            credential_id=CredentialId("cred-service"),
        ),
    )
    validate_credential_binding(
        _service_resource(),
        HttpEgressBinding(
            project_id=_project(),
            credential_id=CredentialId("cred-service"),
            endpoint=NormalizedEndpoint("https://api.example.com"),
            inject=EgressInjectPolicy(
                kind=EgressInjectKind.BEARER,
                credential_field=_field("API_KEY"),
            ),
        ),
    )


@pytest.mark.parametrize("state", [CredentialState.ARCHIVED, CredentialState.DELETED])
def test_binding_policy_rejects_archived_and_deleted_resources(state: CredentialState) -> None:
    with pytest.raises(CredentialPolicyError, match=state.value):
        validate_credential_binding(
            _service_resource(state=state),
            EnvironmentInjectionBinding(
                project_id=_project(),
                credential_id=CredentialId("cred-service"),
            ),
        )


def test_binding_policy_rejects_project_kind_id_and_field_mismatches() -> None:
    with pytest.raises(CredentialPolicyError, match="project"):
        validate_credential_binding(
            _service_resource(),
            EnvironmentInjectionBinding(
                project_id=_project("project-b"),
                credential_id=CredentialId("cred-service"),
            ),
        )
    with pytest.raises(CredentialPolicyError, match="kind"):
        validate_credential_binding(
            _model_resource(),
            EnvironmentInjectionBinding(
                project_id=_project(),
                credential_id=CredentialId("cred-model"),
            ),
        )
    with pytest.raises(CredentialPolicyError, match="credential id"):
        validate_credential_binding(
            _service_resource(),
            EnvironmentInjectionBinding(
                project_id=_project(),
                credential_id=CredentialId("different"),
            ),
        )
    with pytest.raises(CredentialPolicyError, match="field"):
        validate_credential_binding(
            _service_resource(),
            WebhookAuthBinding(
                project_id=_project(),
                credential_id=CredentialId("cred-service"),
                credential_field=_field("MISSING"),
                methods=frozenset({WebhookAuthMethod.HMAC}),
            ),
        )


def test_mcp_policy_rejects_disabled_oauth_and_url_conflicts() -> None:
    group = CredentialGroupResource(
        id=CredentialGroupId("group-a"),
        project_id=_project(),
        name="MCP group",
        state=CredentialState.ACTIVE,
    )
    binding = McpGroupBinding(
        project_id=_project(),
        group_ids=(CredentialGroupId("group-a"),),
        declared_server_urls=(NormalizedMcpUrl("https://mcp.example.com/api"),),
    )

    with pytest.raises(CredentialPolicyError, match="OAUTH2_LEGACY_DISABLED"):
        validate_mcp_group_binding(
            binding, groups=(group,), members=(_mcp_resource(scheme=CredentialAuthScheme.OAUTH2_LEGACY_DISABLED),)
        )

    with pytest.raises(CredentialPolicyError, match="URL conflict"):
        validate_mcp_group_binding(binding, groups=(group,), members=(_mcp_resource(),))


def test_mcp_policy_rejects_archived_or_deleted_groups() -> None:
    binding = McpGroupBinding(
        project_id=_project(),
        group_ids=(CredentialGroupId("group-a"),),
        declared_server_urls=(),
    )
    for state in (CredentialState.ARCHIVED, CredentialState.DELETED):
        group = CredentialGroupResource(
            id=CredentialGroupId("group-a"),
            project_id=_project(),
            name="MCP group",
            state=state,
        )
        with pytest.raises(CredentialPolicyError, match=state.value):
            validate_mcp_group_binding(binding, groups=(group,), members=())


def test_http_injection_shape_is_unambiguous_and_cookie_name_is_a_complete_token() -> None:
    cookie_policy = EgressInjectPolicy(
        kind=EgressInjectKind.COOKIE,
        credential_field=_field("API_KEY"),
        cookie_name="session-token_1",
    )
    header_policy = EgressInjectPolicy(
        kind=EgressInjectKind.API_KEY,
        credential_field=_field("API_KEY"),
        header="X-API-Key",
    )
    assert cookie_policy.cookie_name == "session-token_1"
    assert header_policy.header == "X-API-Key"

    invalid_kwargs = (
        {"kind": EgressInjectKind.BEARER, "header": "Authorization"},
        {"kind": EgressInjectKind.COOKIE, "cookie_name": "session", "header": "X-Auth"},
        {"kind": EgressInjectKind.API_KEY, "header": "X-API-Key", "cookie_name": "session"},
    )
    for kwargs in invalid_kwargs:
        with pytest.raises(ValueError):
            EgressInjectPolicy(credential_field=_field("API_KEY"), **kwargs)

    for invalid_cookie_name in ("bad name", "bad,name", "bad(name)", "密", ""):
        with pytest.raises(ValueError, match="cookie"):
            EgressInjectPolicy(
                kind=EgressInjectKind.COOKIE,
                credential_field=_field("API_KEY"),
                cookie_name=invalid_cookie_name,
            )

    for invalid_header in (" X-API-Key", "X-API-Key "):
        with pytest.raises(ValueError, match="header"):
            EgressInjectPolicy(
                kind=EgressInjectKind.API_KEY,
                credential_field=_field("API_KEY"),
                header=invalid_header,
            )
    for invalid_cookie_name in (" session", "session "):
        with pytest.raises(ValueError, match="cookie"):
            EgressInjectPolicy(
                kind=EgressInjectKind.COOKIE,
                credential_field=_field("API_KEY"),
                cookie_name=invalid_cookie_name,
            )
    with pytest.raises(TypeError, match="header"):
        EgressInjectPolicy(
            kind=EgressInjectKind.API_KEY,
            credential_field=_field("API_KEY"),
            header=123,  # type: ignore[arg-type]
        )
    with pytest.raises(TypeError, match="cookie"):
        EgressInjectPolicy(
            kind=EgressInjectKind.COOKIE,
            credential_field=_field("API_KEY"),
            cookie_name=123,  # type: ignore[arg-type]
        )


def test_lifecycle_archive_restore_delete_and_disabled_restore_rules() -> None:
    archived = decide_credential_lifecycle(_model_resource(), CredentialLifecycleCommand.ARCHIVE)
    assert archived.state is CredentialState.ARCHIVED
    assert archived.is_default is False

    restored = decide_credential_lifecycle(
        _service_resource(state=CredentialState.ARCHIVED),
        CredentialLifecycleCommand.RESTORE,
    )
    assert restored.state is CredentialState.ACTIVE
    assert restored.is_default is False

    restored_model = decide_credential_lifecycle(
        _model_resource(state=CredentialState.ARCHIVED),
        CredentialLifecycleCommand.RESTORE,
    )
    assert restored_model.state is CredentialState.ACTIVE
    assert restored_model.is_default is False

    deleted = decide_credential_lifecycle(
        _service_resource(state=CredentialState.ARCHIVED),
        CredentialLifecycleCommand.DELETE,
    )
    assert deleted.state is CredentialState.DELETED

    with pytest.raises(CredentialLifecycleError, match="OAUTH2_LEGACY_DISABLED"):
        decide_credential_lifecycle(
            _mcp_resource(
                state=CredentialState.ARCHIVED,
                scheme=CredentialAuthScheme.OAUTH2_LEGACY_DISABLED,
            ),
            CredentialLifecycleCommand.RESTORE,
        )
    with pytest.raises(CredentialLifecycleError, match="deleted"):
        decide_credential_lifecycle(
            _service_resource(state=CredentialState.DELETED),
            CredentialLifecycleCommand.RESTORE,
        )


def test_group_lifecycle_uses_the_same_active_archived_deleted_state_machine() -> None:
    group = CredentialGroupResource(
        id=CredentialGroupId("group-a"),
        project_id=_project(),
        name="MCP group",
        state=CredentialState.ACTIVE,
    )
    archived = decide_group_lifecycle(group, CredentialLifecycleCommand.ARCHIVE)
    assert archived.state is CredentialState.ARCHIVED

    restored = decide_group_lifecycle(
        CredentialGroupResource(
            id=group.id,
            project_id=group.project_id,
            name=group.name,
            state=CredentialState.ARCHIVED,
        ),
        CredentialLifecycleCommand.RESTORE,
        restore_context=_group_restore_context(),
    )
    assert restored.state is CredentialState.ACTIVE


def test_group_restore_revalidates_members_and_cross_group_urls() -> None:
    group = CredentialGroupResource(
        id=CredentialGroupId("group-a"),
        project_id=_project(),
        name="MCP group",
        state=CredentialState.ARCHIVED,
    )

    restored = decide_group_lifecycle(
        group,
        CredentialLifecycleCommand.RESTORE,
        restore_context=_group_restore_context(),
    )
    assert restored.state is CredentialState.ACTIVE

    invalid_contexts = (
        _group_restore_context(project_id="project-b"),
        _group_restore_context(members=(_mcp_resource(project_id="project-b"),)),
        _group_restore_context(members=(_mcp_resource(state=CredentialState.ARCHIVED),)),
        _group_restore_context(members=(_mcp_resource(scheme=CredentialAuthScheme.OAUTH2_LEGACY_DISABLED),)),
        _group_restore_context(members=(_mcp_resource(fields=("other",)),)),
        _group_restore_context(members=(_mcp_resource(group_id="group-b"),)),
        _group_restore_context(occupied_server_urls=frozenset({NormalizedMcpUrl("https://mcp.example.com/api")})),
    )
    for context in invalid_contexts:
        with pytest.raises((CredentialLifecycleError, CredentialPolicyError)):
            decide_group_lifecycle(group, CredentialLifecycleCommand.RESTORE, restore_context=context)

    with pytest.raises(CredentialLifecycleError, match="context"):
        decide_group_lifecycle(group, CredentialLifecycleCommand.RESTORE)


def test_dependency_descriptors_are_metadata_only_and_operation_specific() -> None:
    descriptor = ReferenceSurfaceDescriptor(
        surface_id="environment-live-binding",
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset(
            {
                DependencyDisposition.BLOCK_RESOURCE_ARCHIVE,
                DependencyDisposition.BLOCK_RESOURCE_DELETE,
                DependencyDisposition.REFRESH_RUNTIME_POLICY,
            }
        ),
        scanner_id="environment-scanner",
        owner="environment",
        persistent=True,
    )
    dependency = CredentialDependency(
        surface_id=descriptor.surface_id,
        project_id=_project(),
        source_id="env-a",
        credential_id=CredentialId("cred-service"),
        group_id=None,
        dispositions=descriptor.dispositions,
    )
    impact = CredentialImpact(
        usage=CredentialUsage.ENVIRONMENT_INJECTION,
        source="environment",
        project_id=_project(),
        affected_sandbox_ids=frozenset({"sandbox-a"}),
        affected_session_ids=frozenset(),
        dispositions=frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY}),
    )

    assert descriptor.scanner_id == "environment-scanner"
    assert dependency.blocks(DependencyDisposition.BLOCK_RESOURCE_ARCHIVE)
    assert impact.dispositions == frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY})
    assert {field.name for field in fields(ReferenceSurfaceDescriptor)} == {
        "surface_id",
        "kind",
        "target",
        "dispositions",
        "scanner_id",
        "owner",
        "persistent",
    }


def test_reference_objects_are_typed_metadata_without_material_or_adapters() -> None:
    reference = CredentialReference(
        kind=CredentialReferenceKind.RESOURCE,
        project_id=_project(),
        source="environment",
        source_id="env-a",
        credential_id=CredentialId("cred-service"),
        group_id=None,
    )

    assert reference.kind is CredentialReferenceKind.RESOURCE
    assert {field.name for field in fields(CredentialReference)} == {
        "kind",
        "project_id",
        "source",
        "source_id",
        "credential_id",
        "group_id",
    }


def test_pydantic_credential_schema_preserves_domain_enum_compatibility() -> None:
    request = CreateCredentialRequest(kind="model", name="  Example  ", data={"API_KEY": "value"})

    assert request.kind is CredentialKind.MODEL
    assert request.name == "Example"
    assert request.model_dump(mode="json")["kind"] == "model"
    assert CreateCredentialRequest.model_fields["kind"].annotation is CredentialKind
    assert TypeAdapter(CredentialKind).json_schema()["enum"] == ["model", "service", "mcp"]
    with pytest.raises(ValidationError):
        CreateCredentialRequest(kind="llm", name="Example")
