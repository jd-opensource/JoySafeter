import ast
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from error_contract_helpers import handled_app_error_payload
from fastapi.responses import StreamingResponse

from app.joysafeter_api.api.v1 import quickstart as quickstart_module
from app.joysafeter_api.api.v1 import skills_ai_authoring as authoring_module
from app.joysafeter_api.api.v1.quickstart import (
    QuickstartChatRequest,
    QuickstartMessage,
    quickstart_chat,
)
from app.joysafeter_api.api.v1.skills_ai_authoring import (
    AuthoringChatRequest,
    AuthoringMessage,
    authoring_chat,
)
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.snapshot_service import NoPersistentDependencyScanner
from app.joysafeter_domain.credentials.bindings import ModelInferenceBinding
from app.joysafeter_domain.credentials.dependencies import ReferenceSurfaceKind
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.model_inference_policy import build_model_inference_policy
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.schemas.joysafeter_credential import CreateCredentialRequest
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_infrastructure.credentials.material_adapter import ManagedCredentialMaterialAdapter
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.ids import CredentialId

APP_ROOT = Path(__file__).parents[1] / "app"
ENDPOINT_PATHS = (
    APP_ROOT / "joysafeter_api/api/v1/quickstart.py",
    APP_ROOT / "joysafeter_api/api/v1/skills_ai_authoring.py",
)
AGENT_SERVICE_PATH = APP_ROOT / "joysafeter_domain/services/joysafeter_agent_service.py"


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


def _auth_ctx(project_id: str) -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=project_id,
        role=JoySafeterRole.MEMBER,
    )


async def _make_model_credential(
    db_session,
    project_id: str,
    *,
    provider: str = "openai",
    protocol: str = "openai_responses",
    data: dict[str, str] | None = None,
) -> CredentialId:
    credential = await CredentialService(db_session).create(
        CreateCredentialRequest(
            kind="model",
            name=f"model-{uuid.uuid4()}",
            provider=provider,
            protocol=protocol,
            data=(data if data is not None else {"OPENAI_API_KEY": "secret", "OPENAI_MODEL": "gpt-5.5"}),
        ),
        project_id=project_id,
    )
    return credential.id


async def _invoke(endpoint: str, credential_id: CredentialId, db_session, project_id: str):
    if endpoint == "quickstart":
        return await quickstart_chat(
            QuickstartChatRequest(
                model_credential_id=credential_id,
                engine_kind="codex",
                messages=[QuickstartMessage(role="user", content="Configure an agent")],
            ),
            db_session,
            _auth_ctx(project_id),
        )
    return await authoring_chat(
        AuthoringChatRequest(
            model_credential_id=credential_id,
            messages=[AuthoringMessage(role="user", content="Draft a skill")],
        ),
        db_session,
        _auth_ctx(project_id),
    )


def _binding_error_contract(endpoint: str, credential_id: CredentialId, code: str) -> tuple[int, dict]:
    data = {"credential_id": str(credential_id)}
    if endpoint == "quickstart":
        data["engine_kind"] = "codex"
    contracts = {
        "CREDENTIAL_NOT_FOUND": (
            404,
            {
                "code": "CREDENTIAL_NOT_FOUND",
                "message": "Credential not found",
                "data": data,
                "source": "api",
                "retryable": False,
                "user_action": "fix_input",
            },
        ),
        "CREDENTIAL_STATE_INVALID": (
            409,
            {
                "code": "CREDENTIAL_STATE_INVALID",
                "message": "Credential state is invalid for this operation",
                "data": data,
                "source": "api",
                "retryable": False,
                "user_action": "refresh",
            },
        ),
        "CREDENTIAL_KIND_INVALID": (
            400,
            {
                "code": "CREDENTIAL_KIND_INVALID",
                "message": "Credential kind is invalid for this operation",
                "data": data,
                "source": "api",
                "retryable": False,
                "user_action": "fix_input",
            },
        ),
        "CREDENTIAL_CORRUPT": (
            400,
            {
                "code": "CREDENTIAL_CORRUPT",
                "message": "Credential record is corrupt",
                "data": data,
                "source": "api",
                "retryable": False,
                "user_action": "refresh",
            },
        ),
    }
    return contracts[code]


async def _assert_binding_error_contract(
    endpoint: str,
    credential_id: CredentialId,
    exc: AppError,
    code: str,
) -> None:
    status_code, expected = _binding_error_contract(endpoint, credential_id, code)
    payload = await handled_app_error_payload(exc, status_code=status_code)
    assert payload == expected
    serialized = json.dumps(payload, sort_keys=True)
    assert "secret" not in serialized
    assert "not-an-envelope" not in serialized


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_reject_archived_credentials(endpoint, db_session, project_id):
    credential_id = await _make_model_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.archived_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await _invoke(endpoint, credential_id, db_session, project_id)

    await _assert_binding_error_contract(
        endpoint,
        credential_id,
        exc_info.value,
        "CREDENTIAL_STATE_INVALID",
    )


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_hide_deleted_credentials(endpoint, db_session, project_id):
    credential_id = await _make_model_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await _invoke(endpoint, credential_id, db_session, project_id)

    await _assert_binding_error_contract(endpoint, credential_id, exc_info.value, "CREDENTIAL_NOT_FOUND")


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_hide_wrong_project_credentials(endpoint, db_session, project_id):
    other_project_id = await _make_project(db_session)
    credential_id = await _make_model_credential(db_session, other_project_id)

    with pytest.raises(AppError) as exc_info:
        await _invoke(endpoint, credential_id, db_session, project_id)

    await _assert_binding_error_contract(endpoint, credential_id, exc_info.value, "CREDENTIAL_NOT_FOUND")


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_reject_incompatible_catalog_binding(endpoint, db_session, project_id):
    credential_id = await _make_model_credential(
        db_session,
        project_id,
        provider="anthropic",
        protocol="anthropic_messages",
        data={"ANTHROPIC_API_KEY": "secret"},
    )

    with pytest.raises(AppError) as exc_info:
        await _invoke(endpoint, credential_id, db_session, project_id)

    await _assert_binding_error_contract(endpoint, credential_id, exc_info.value, "CREDENTIAL_KIND_INVALID")


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_fail_closed_on_corrupt_material(endpoint, db_session, project_id):
    credential_id = await _make_model_credential(db_session, project_id)
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    credential.data = {"OPENAI_API_KEY": "not-an-envelope"}
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await _invoke(endpoint, credential_id, db_session, project_id)

    await _assert_binding_error_contract(endpoint, credential_id, exc_info.value, "CREDENTIAL_CORRUPT")


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_reject_disabled_engines(
    endpoint,
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_model_credential(db_session, project_id)
    catalog = get_llm_catalog().model_copy(deep=True)
    catalog.engine("codex").enabled = False
    endpoint_module = quickstart_module if endpoint == "quickstart" else authoring_module
    monkeypatch.setattr(endpoint_module, "get_llm_catalog", lambda: catalog)

    with pytest.raises(AppError) as exc_info:
        await _invoke(endpoint, credential_id, db_session, project_id)

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "LLM_ENGINE_DISABLED",
        "message": "LLM engine is disabled: codex",
        "data": {"engine_kind": "codex"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.parametrize("endpoint", ["quickstart", "authoring"])
@pytest.mark.asyncio
async def test_ephemeral_consumers_load_only_catalog_authorized_material(
    endpoint,
    db_session,
    project_id,
    monkeypatch,
):
    credential_id = await _make_model_credential(
        db_session,
        project_id,
        data={
            "OPENAI_API_KEY": "secret",
            "OPENAI_MODEL": "gpt-5.5",
            "UNRELATED_SECRET": "must-not-load",
        },
    )
    loaded_fields: list[set[str]] = []
    original_load = ManagedCredentialMaterialAdapter.load

    async def observe_load(self, validated):
        loaded_fields.append({str(field_name) for field_name in validated.authorized_fields})
        resolved = await original_load(self, validated)
        assert "secret" not in repr(resolved)
        assert "must-not-load" not in repr(resolved)
        return resolved

    monkeypatch.setattr(ManagedCredentialMaterialAdapter, "load", observe_load)

    response = await _invoke(endpoint, credential_id, db_session, project_id)

    assert isinstance(response, StreamingResponse)
    assert loaded_fields == [{"OPENAI_API_KEY", "OPENAI_MODEL"}]
    credential = await CredentialService(db_session).get(credential_id, project_id=project_id)
    assert credential.data["OPENAI_API_KEY"].startswith("enc:v1:")
    assert credential.data["UNRELATED_SECRET"].startswith("enc:v1:")


def test_ephemeral_consumers_share_agent_model_inference_policy_builder() -> None:
    for path in (*ENDPOINT_PATHS, AGENT_SERVICE_PATH):
        source = path.read_text()
        assert "build_model_inference_policy" in source, path
        assert "ModelInferenceBinding(" not in source, path


def test_model_inference_policy_rejects_disabled_engine_before_candidates() -> None:
    catalog = get_llm_catalog().model_copy(deep=True)
    catalog.engine("codex").enabled = False

    with pytest.raises(ValueError, match="disabled"):
        build_model_inference_policy(
            catalog,
            project_id="project-1",
            credential_id="credential-1",
            engine_kind="codex",
            model_id=None,
        )


@pytest.mark.asyncio
async def test_model_inference_builder_returns_only_binding_and_service_resolves_catalog(
    db_session,
    project_id,
) -> None:
    credential_id = await _make_model_credential(db_session, project_id)
    application = compose_credential_application(
        db_session,
        auto_commit=False,
        compatibility_mode=False,
    )
    binding = build_model_inference_policy(
        get_llm_catalog(),
        project_id=project_id,
        credential_id=credential_id,
        engine_kind="codex",
        model_id=None,
    )

    assert isinstance(binding, ModelInferenceBinding)
    assert not hasattr(binding, "authorizations")
    assert not hasattr(binding, "candidates")
    assert not hasattr(binding, "authorized_fields")

    validated, resolution = await application.binding_service.validate_model_inference(binding)

    assert validated.binding is binding
    assert validated.authorized_fields == {"OPENAI_API_KEY", "OPENAI_MODEL"}
    assert resolution.credential_profile_id == "openai_bearer"


def test_model_inference_policy_module_has_no_authorization_issuance_api() -> None:
    from app.joysafeter_domain.llm import model_inference_policy

    for forbidden in (
        "ModelInferenceCatalogAuthorization",
        "ModelInferencePolicy",
        "verify_model_inference_catalog_authorization",
    ):
        assert not hasattr(model_inference_policy, forbidden)


@pytest.mark.asyncio
async def test_forged_catalog_like_object_fails_before_material_load(
    db_session,
    project_id,
    monkeypatch,
) -> None:
    credential_id = await _make_model_credential(db_session, project_id)
    forged_binding = SimpleNamespace(
        project_id=project_id,
        credential_id=credential_id,
        engine_kind="codex",
        model_id=None,
        provider_id="openai",
        protocol_id="openai_responses",
        authorized_fields=frozenset({"UNRELATED_SECRET"}),
    )
    monkeypatch.setattr(
        quickstart_module,
        "build_model_inference_policy",
        lambda *args, **kwargs: forged_binding,
    )
    material_loaded = False
    original_load = ManagedCredentialMaterialAdapter.load

    async def observe_load(self, validated):
        nonlocal material_loaded
        material_loaded = True
        return await original_load(self, validated)

    monkeypatch.setattr(ManagedCredentialMaterialAdapter, "load", observe_load)

    with pytest.raises(AppError) as exc_info:
        await _invoke("quickstart", credential_id, db_session, project_id)

    assert exc_info.value.code == "CREDENTIAL_CORRUPT"
    assert material_loaded is False


@pytest.mark.asyncio
async def test_tampered_binding_fails_before_material_load(
    db_session,
    project_id,
    monkeypatch,
) -> None:
    credential_id = await _make_model_credential(db_session, project_id)
    binding = build_model_inference_policy(
        get_llm_catalog(),
        project_id=project_id,
        credential_id=credential_id,
        engine_kind="codex",
        model_id=None,
    )
    assert isinstance(binding, ModelInferenceBinding)
    object.__setattr__(binding, "engine_kind", "codex")
    monkeypatch.setattr(quickstart_module, "build_model_inference_policy", lambda *args, **kwargs: binding)
    material_loaded = False
    original_load = ManagedCredentialMaterialAdapter.load

    async def observe_load(self, validated):
        nonlocal material_loaded
        material_loaded = True
        return await original_load(self, validated)

    monkeypatch.setattr(ManagedCredentialMaterialAdapter, "load", observe_load)

    with pytest.raises(AppError) as exc_info:
        await _invoke("quickstart", credential_id, db_session, project_id)

    assert exc_info.value.code == "CREDENTIAL_CORRUPT"
    assert material_loaded is False


def test_ephemeral_descriptors_use_explicit_no_persistent_scanners(db_session) -> None:
    application = compose_credential_application(
        db_session,
        auto_commit=False,
        compatibility_mode=False,
    )
    descriptors = {
        str(descriptor.surface_id): descriptor
        for descriptor in application.snapshot_service.descriptors
        if descriptor.kind is ReferenceSurfaceKind.EPHEMERAL_CONSUMER
    }

    for surface_id in ("quickstart_model_inference", "skill_ai_authoring_model_inference"):
        descriptor = descriptors[surface_id]
        scanner = application.snapshot_service.scanner(descriptor.scanner_id)
        assert descriptor.persistent is False
        assert isinstance(scanner, NoPersistentDependencyScanner)
        assert scanner.reason == "ephemeral_consumer"


def test_no_persistent_dependency_scanner_rejects_invalid_reason() -> None:
    with pytest.raises(ValueError, match="ephemeral_consumer"):
        NoPersistentDependencyScanner(
            scanner_id="invalid-reason-scanner",
            reason="persistent",  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_ephemeral_scanners_never_create_persistent_dependencies(db_session, project_id) -> None:
    application = compose_credential_application(
        db_session,
        auto_commit=False,
        compatibility_mode=False,
    )
    credential_id = await _make_model_credential(db_session, project_id)

    for descriptor in application.snapshot_service.descriptors:
        if str(descriptor.surface_id) not in {
            "quickstart_model_inference",
            "skill_ai_authoring_model_inference",
        }:
            continue
        scanner = application.snapshot_service.scanner(descriptor.scanner_id)
        assert await scanner.scan_resource(project_id, credential_id) == ()


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


@dataclass
class _EndpointPathState:
    provenance: dict[str, tuple[object, ...]]
    violations: set[str] = field(default_factory=set)
    material_loads: list[tuple[bool, bool]] = field(default_factory=list)
    control: str | None = None

    def fork(self) -> "_EndpointPathState":
        return _EndpointPathState(
            provenance=self.provenance.copy(),
            violations=self.violations.copy(),
            material_loads=self.material_loads.copy(),
            control=self.control,
        )


def _ephemeral_endpoint_boundary_violations(source: str, *, require_flow: bool) -> set[str]:
    tree = ast.parse(source)
    sensitive_attributes = {
        "archived_at",
        "data",
        "deleted_at",
        "kind",
        "material",
        "protocol",
        "provider",
        "state",
    }
    forbidden_calls = {
        "CredentialService",
        "LegacyV1MaterialProtector",
        "decrypt",
        "decrypt_data",
        "get_credential_data",
        "reveal",
        "reveal_values",
    }
    forbidden_import_fragments = {
        "joysafeter_domain.services.joysafeter_credential_service",
        "joysafeter_infrastructure.credentials.material_adapter",
        "joysafeter_infrastructure.credentials.sqlalchemy_repository",
        "joysafeter_infrastructure.sensitive_material",
    }
    canonical_call_symbols = {
        "build_model_inference_policy": {
            "app.joysafeter_domain.llm.model_inference_policy.build_model_inference_policy",
            "build_model_inference_policy",
        },
        "compose_credential_application": {
            "app.joysafeter_application.credentials.composition.compose_credential_application",
            "compose_credential_application",
        },
    }
    imported_modules: set[str] = set()
    import_aliases: dict[str, str] = {}
    locally_defined_symbols = {
        node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)
            for alias in node.names:
                import_aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name)
                import_aliases[alias.asname or alias.name.split(".", maxsplit=1)[0]] = alias.name
    violations: set[str] = set()
    if any(
        fragment in imported_module for imported_module in imported_modules for fragment in forbidden_import_fragments
    ):
        violations.add("forbidden_import")

    def canonical_dotted(node: ast.AST) -> str | None:
        dotted = _dotted_name(node)
        if dotted is None:
            return None
        root, separator, remainder = dotted.partition(".")
        canonical_root = import_aliases.get(root, root)
        return f"{canonical_root}.{remainder}" if separator else canonical_root

    def distinct_states(states: list[_EndpointPathState]) -> list[_EndpointPathState]:
        unique: dict[tuple[object, ...], _EndpointPathState] = {}
        for state in states:
            key = (
                tuple(sorted(state.provenance.items())),
                frozenset(state.violations),
                tuple(state.material_loads),
                state.control,
            )
            unique.setdefault(key, state)
        return list(unique.values())

    def constant_truth(node: ast.AST) -> bool | None:
        if isinstance(node, ast.Constant):
            return bool(node.value)
        return None

    function_results: list[tuple[str, list[_EndpointPathState]]] = []
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for function in functions:
        provenance: dict[str, tuple[object, ...]] = {}
        arguments = [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]
        if function.args.vararg is not None:
            arguments.append(function.args.vararg)
        if function.args.kwarg is not None:
            arguments.append(function.args.kwarg)
        for argument in arguments:
            lowered = argument.arg.lower()
            if lowered == "application":
                provenance[argument.arg] = ("application", (function.name, "argument"), False)
            elif any(token in lowered for token in ("credentials", "repository")):
                provenance[argument.arg] = ("repository",)

        def terminal_name(value: tuple[object, ...] | None) -> str:
            if value is None or value[0] != "symbol":
                return ""
            return str(value[1]).rsplit(".", maxsplit=1)[-1]

        def operation_name(value: tuple[object, ...] | None) -> str:
            operation = terminal_name(value)
            allowed_symbols = canonical_call_symbols.get(operation)
            if allowed_symbols is None or value is None:
                return operation
            symbol = str(value[1])
            if symbol not in allowed_symbols:
                return ""
            if symbol == operation and operation in locally_defined_symbols:
                return ""
            return operation

        def expression_provenance(
            node: ast.AST,
            state: _EndpointPathState,
        ) -> tuple[object, ...] | None:
            if isinstance(node, ast.Await):
                return expression_provenance(node.value, state)
            if isinstance(node, ast.NamedExpr):
                value = expression_provenance(node.value, state)
                assign(node.target, value, state)
                return value
            if isinstance(node, ast.Name):
                value = state.provenance.get(node.id)
                if value is not None:
                    return value
                dotted = canonical_dotted(node)
                return ("symbol", dotted) if dotted is not None else None
            if isinstance(node, ast.Attribute):
                receiver = expression_provenance(node.value, state)
                if receiver is not None and receiver[0] == "sensitive" and node.attr in sensitive_attributes:
                    state.violations.add(f"attribute:{node.attr}")
                if receiver is not None and receiver[0] == "application":
                    if node.attr == "binding_service":
                        return ("binding_service", receiver[1], receiver[2])
                    if node.attr == "material_adapter":
                        return ("material_adapter", receiver[1], receiver[2])
                if "repository" in node.attr.lower() or node.attr == "credentials":
                    return ("repository",)
                if receiver is not None and receiver[0] == "binding_service":
                    if node.attr == "validate_model_inference":
                        return ("callable", "validate_model_inference", receiver[1], receiver[2])
                    if node.attr in {"validate", "validate_reference"}:
                        return ("callable", "generic_validation")
                if receiver is not None and receiver[0] == "material_adapter" and node.attr == "load":
                    return ("callable", "material_load", receiver[1], receiver[2])
                if (
                    receiver is not None
                    and receiver[0] == "repository"
                    and node.attr
                    in {
                        "get",
                        "get_resource",
                        "load_encrypted_material",
                    }
                ):
                    return ("callable", "repository", node.attr)
                if node.attr in forbidden_calls:
                    return ("callable", "forbidden", node.attr)
                if receiver is not None and receiver[0] == "symbol":
                    return ("symbol", f"{receiver[1]}.{node.attr}")
                dotted = canonical_dotted(node)
                return ("symbol", dotted) if dotted is not None else None
            if isinstance(node, ast.Call):
                callable_value = expression_provenance(node.func, state)
                call_arguments = [expression_provenance(argument, state) for argument in node.args]
                for keyword in node.keywords:
                    expression_provenance(keyword.value, state)
                if any(keyword.arg == "requested_fields" for keyword in node.keywords):
                    state.violations.add("requested_fields")
                operation = operation_name(callable_value)
                if callable_value is not None and callable_value[0] == "callable":
                    operation = str(callable_value[1])
                if operation == "compose_credential_application":
                    canonical = any(
                        keyword.arg == "compatibility_mode"
                        and isinstance(keyword.value, ast.Constant)
                        and keyword.value.value is False
                        for keyword in node.keywords
                    )
                    return ("application", (function.name, node.lineno, node.col_offset), canonical)
                if operation == "build_model_inference_policy":
                    return ("binding", (function.name, node.lineno, node.col_offset))
                if operation == "validate_model_inference":
                    if (
                        callable_value is not None
                        and len(callable_value) == 4
                        and call_arguments
                        and call_arguments[0] is not None
                        and call_arguments[0][0] == "binding"
                    ):
                        return (
                            "validation_result",
                            callable_value[2],
                            callable_value[3],
                            call_arguments[0][1],
                        )
                    return None
                if operation == "material_load":
                    connected = bool(
                        callable_value is not None
                        and len(callable_value) == 4
                        and call_arguments
                        and call_arguments[0] is not None
                        and call_arguments[0][0] == "validated"
                        and call_arguments[0][1] == callable_value[2]
                    )
                    canonical = bool(
                        connected
                        and callable_value is not None
                        and callable_value[3]
                        and call_arguments[0] is not None
                        and call_arguments[0][2]
                    )
                    state.material_loads.append((connected, canonical))
                    return ("sensitive",)
                if operation == "repository" and callable_value is not None:
                    repository_method = str(callable_value[2])
                    state.violations.add(f"repository_call:{repository_method}")
                    return ("sensitive",)
                if operation == "generic_validation":
                    state.violations.add("generic_validation")
                    return None
                if operation == "CredentialService":
                    state.violations.add("call:CredentialService")
                    return ("repository",)
                if operation in forbidden_calls:
                    state.violations.add(f"call:{operation}")
                    return ("sensitive",)
                if operation == "forbidden" and callable_value is not None:
                    forbidden_name = str(callable_value[2])
                    state.violations.add(f"call:{forbidden_name}")
                    return ("sensitive",)
                return None
            if isinstance(node, ast.Subscript):
                value = expression_provenance(node.value, state)
                expression_provenance(node.slice, state)
                if (
                    value is not None
                    and value[0] == "validation_result"
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == 0
                ):
                    return ("validated", value[1], value[2], value[3])
                return None
            if isinstance(node, (ast.Tuple, ast.List)):
                return ("sequence", *(expression_provenance(element, state) for element in node.elts))
            if isinstance(node, ast.IfExp):
                expression_provenance(node.test, state)
                truth = constant_truth(node.test)
                if truth is not None:
                    branch = node.body if truth else node.orelse
                    return expression_provenance(branch, state)
                body_state = state.fork()
                else_state = state.fork()
                body_value = expression_provenance(node.body, body_state)
                else_value = expression_provenance(node.orelse, else_state)
                state.violations.update(body_state.violations)
                state.violations.update(else_state.violations)
                state.material_loads = list(dict.fromkeys((*body_state.material_loads, *else_state.material_loads)))
                state.provenance = {
                    name: value
                    for name, value in body_state.provenance.items()
                    if else_state.provenance.get(name) == value
                }
                return body_value if body_value == else_value else None
            if isinstance(node, ast.Lambda):
                return None
            for child in ast.iter_child_nodes(node):
                expression_provenance(child, state)
            return None

        def assign(
            target: ast.AST,
            value: tuple[object, ...] | None,
            state: _EndpointPathState,
        ) -> None:
            if isinstance(target, ast.Name):
                if value is None:
                    state.provenance.pop(target.id, None)
                else:
                    state.provenance[target.id] = value
                return
            if not isinstance(target, (ast.Tuple, ast.List)):
                return
            values: tuple[object, ...] = ()
            if value is not None and value[0] == "validation_result":
                values = (("validated", value[1], value[2], value[3]), ("resolution",))
            elif value is not None and value[0] == "sequence":
                values = value[1:]
            for index, element in enumerate(target.elts):
                element_value = values[index] if index < len(values) else None
                assign(element, element_value if isinstance(element_value, tuple) else None, state)

        def process_statements(
            statements: list[ast.stmt],
            states: list[_EndpointPathState],
            *,
            exception_seeds: list[_EndpointPathState] | None = None,
        ) -> list[_EndpointPathState]:
            current_states = distinct_states(states)
            for statement in statements:
                next_states: list[_EndpointPathState] = []
                for state in current_states:
                    if state.control is not None:
                        next_states.append(state)
                        continue
                    if exception_seeds is not None:
                        exception_seeds.append(state.fork())
                    next_states.extend(process_statement(statement, state, exception_seeds))
                current_states = distinct_states(next_states)
            return current_states

        def process_loop_exit(
            paths: list[_EndpointPathState],
            orelse: list[ast.stmt],
            exception_seeds: list[_EndpointPathState] | None,
        ) -> list[_EndpointPathState]:
            results: list[_EndpointPathState] = []
            normal_exits: list[_EndpointPathState] = []
            for path in paths:
                if path.control == "break":
                    path.control = None
                    results.append(path)
                elif path.control == "continue":
                    path.control = None
                    normal_exits.append(path)
                elif path.control is None:
                    normal_exits.append(path)
                else:
                    results.append(path)
            results.extend(
                process_statements(
                    orelse,
                    normal_exits,
                    exception_seeds=exception_seeds,
                )
            )
            return distinct_states(results)

        def process_statement(
            statement: ast.stmt,
            state: _EndpointPathState,
            exception_seeds: list[_EndpointPathState] | None,
        ) -> list[_EndpointPathState]:
            if isinstance(statement, ast.Assign):
                value = expression_provenance(statement.value, state)
                for target in statement.targets:
                    assign(target, value, state)
                return [state]
            if isinstance(statement, ast.AnnAssign):
                value = expression_provenance(statement.value, state) if statement.value is not None else None
                assign(statement.target, value, state)
                return [state]
            if isinstance(statement, ast.AugAssign):
                expression_provenance(statement.target, state)
                expression_provenance(statement.value, state)
                assign(statement.target, None, state)
                return [state]
            if isinstance(statement, ast.Expr):
                expression_provenance(statement.value, state)
                return [state]
            if isinstance(statement, ast.Return):
                if statement.value is not None:
                    expression_provenance(statement.value, state)
                state.control = "return"
                return [state]
            if isinstance(statement, ast.Raise):
                if statement.exc is not None:
                    expression_provenance(statement.exc, state)
                if statement.cause is not None:
                    expression_provenance(statement.cause, state)
                state.control = "raise"
                return [state]
            if isinstance(statement, ast.Break):
                state.control = "break"
                return [state]
            if isinstance(statement, ast.Continue):
                state.control = "continue"
                return [state]
            if isinstance(statement, ast.If):
                expression_provenance(statement.test, state)
                truth = constant_truth(statement.test)
                branches: list[_EndpointPathState] = []
                if truth is not False:
                    branches.extend(
                        process_statements(
                            statement.body,
                            [state.fork()],
                            exception_seeds=exception_seeds,
                        )
                    )
                if truth is not True:
                    branches.extend(
                        process_statements(
                            statement.orelse,
                            [state.fork()],
                            exception_seeds=exception_seeds,
                        )
                    )
                return distinct_states(branches)
            if isinstance(statement, (ast.Try, ast.TryStar)):
                local_exception_seeds: list[_EndpointPathState] = []
                body_results = process_statements(
                    statement.body,
                    [state.fork()],
                    exception_seeds=local_exception_seeds,
                )
                handler_seeds = local_exception_seeds.copy()
                for body_state in body_results:
                    if body_state.control == "raise":
                        caught_state = body_state.fork()
                        caught_state.control = None
                        handler_seeds.append(caught_state)

                normal_body = [path for path in body_results if path.control is None]
                completed_paths = process_statements(
                    statement.orelse,
                    normal_body,
                    exception_seeds=exception_seeds,
                )
                completed_paths.extend(path for path in body_results if path.control is not None)

                for handler in statement.handlers:
                    for handler_seed in distinct_states(handler_seeds):
                        handler_state = handler_seed.fork()
                        handler_state.control = None
                        if handler.type is not None:
                            expression_provenance(handler.type, handler_state)
                        if handler.name is not None:
                            handler_state.provenance.pop(handler.name, None)
                        completed_paths.extend(
                            process_statements(
                                handler.body,
                                [handler_state],
                                exception_seeds=exception_seeds,
                            )
                        )

                completed_paths = distinct_states(completed_paths)
                if not statement.finalbody:
                    return completed_paths
                final_paths: list[_EndpointPathState] = []
                for completed_path in completed_paths:
                    prior_control = completed_path.control
                    final_input = completed_path.fork()
                    final_input.control = None
                    for final_path in process_statements(
                        statement.finalbody,
                        [final_input],
                        exception_seeds=exception_seeds,
                    ):
                        if final_path.control is None:
                            final_path.control = prior_control
                        final_paths.append(final_path)
                return distinct_states(final_paths)
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                expression_provenance(statement.iter, state)
                zero_iteration = state.fork()
                one_iteration = state.fork()
                assign(statement.target, None, one_iteration)
                body_results = process_statements(
                    statement.body,
                    [one_iteration],
                    exception_seeds=exception_seeds,
                )
                return process_loop_exit(
                    [zero_iteration, *body_results],
                    statement.orelse,
                    exception_seeds,
                )
            if isinstance(statement, ast.While):
                expression_provenance(statement.test, state)
                truth = constant_truth(statement.test)
                loop_paths: list[_EndpointPathState] = []
                if truth is not True:
                    loop_paths.append(state.fork())
                if truth is not False:
                    loop_paths.extend(
                        process_statements(
                            statement.body,
                            [state.fork()],
                            exception_seeds=exception_seeds,
                        )
                    )
                return process_loop_exit(loop_paths, statement.orelse, exception_seeds)
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    context = expression_provenance(item.context_expr, state)
                    if item.optional_vars is not None:
                        assign(item.optional_vars, context, state)
                return process_statements(
                    statement.body,
                    [state],
                    exception_seeds=exception_seeds,
                )
            if isinstance(statement, ast.Match):
                expression_provenance(statement.subject, state)
                case_paths = [state.fork()]
                for case in statement.cases:
                    case_state = state.fork()
                    for pattern_node in ast.walk(case.pattern):
                        pattern_name = getattr(pattern_node, "name", None)
                        if isinstance(pattern_name, str):
                            case_state.provenance.pop(pattern_name, None)
                    if case.guard is not None:
                        expression_provenance(case.guard, case_state)
                        if constant_truth(case.guard) is False:
                            continue
                    case_paths.extend(
                        process_statements(
                            case.body,
                            [case_state],
                            exception_seeds=exception_seeds,
                        )
                    )
                return distinct_states(case_paths)
            if isinstance(statement, ast.Assert):
                expression_provenance(statement.test, state)
                if statement.msg is not None:
                    expression_provenance(statement.msg, state)
                return [state]
            if isinstance(statement, ast.Delete):
                for target in statement.targets:
                    if isinstance(target, ast.Name):
                        state.provenance.pop(target.id, None)
                    else:
                        expression_provenance(target, state)
                return [state]
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                state.provenance.pop(statement.name, None)
                return [state]
            for _field_name, field_value in ast.iter_fields(statement):
                if isinstance(field_value, ast.expr):
                    expression_provenance(field_value, state)
                elif isinstance(field_value, list):
                    for item in field_value:
                        if isinstance(item, ast.expr):
                            expression_provenance(item, state)
            return [state]

        initial_state = _EndpointPathState(provenance=provenance)
        final_states = process_statements(function.body, [initial_state])
        function_results.append((function.name, final_states))
        for state in final_states:
            violations.update(state.violations)

    if require_flow:
        endpoint_names = {"authoring_chat", "endpoint", "quickstart_chat"}
        endpoint_results = [result for result in function_results if result[0] in endpoint_names]
        if not endpoint_results:
            endpoint_results = function_results
        if not endpoint_results:
            violations.add("model_flow")
            violations.add("canonical_composition")
        for _function_name, states in endpoint_results:
            material_loads = [load for state in states for load in state.material_loads]
            if not material_loads or any(not connected for connected, _canonical in material_loads):
                violations.add("model_flow")
            if not material_loads or any(not canonical for _connected, canonical in material_loads):
                violations.add("canonical_composition")
    return violations


@pytest.mark.no_db
@pytest.mark.parametrize("path", ENDPOINT_PATHS, ids=("quickstart", "skill_authoring"))
def test_ephemeral_endpoint_ast_guards(path: Path) -> None:
    assert _ephemeral_endpoint_boundary_violations(path.read_text(), require_flow=True) == set(), path


@pytest.mark.no_db
def test_ephemeral_endpoint_ast_guard_allows_unrelated_local_state_and_data() -> None:
    source = """
def helper(request, response):
    local_state = request.state
    local_data = response.data
    return local_state, local_data
"""

    assert _ephemeral_endpoint_boundary_violations(source, require_flow=False) == set()


@pytest.mark.no_db
def test_ephemeral_endpoint_ast_guard_reassignment_clears_sensitive_provenance() -> None:
    source = """
async def helper(credential_repository, credential_id, response):
    row = await credential_repository.get(credential_id)
    row = response
    return row.data
"""

    violations = _ephemeral_endpoint_boundary_violations(source, require_flow=False)

    assert violations == {"repository_call:get"}


@pytest.mark.no_db
def test_ephemeral_endpoint_ast_guard_accepts_connected_alias_flow() -> None:
    source = """
async def endpoint(project_id, credential_id):
    composer = compose_credential_application
    builder = build_model_inference_policy
    application = composer(db, compatibility_mode=False)
    validator = application.binding_service.validate_model_inference
    loader = application.material_adapter.load
    binding = builder(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    binding_alias = binding
    validation_result = await validator(binding_alias)
    validated = validation_result[0]
    validated_alias = validated
    material = await loader(validated_alias)
    return material.fields
"""

    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == set()


@pytest.mark.no_db
@pytest.mark.parametrize(
    "source",
    [
        """
async def endpoint(project_id, credential_id, decoy):
    composer = decoy.compose_credential_application
    builder = decoy.build_model_inference_policy
    application = composer(db, compatibility_mode=False)
    binding = builder(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validator = application.binding_service.validate_model_inference
    validated, resolution = await validator(binding)
    loader = application.material_adapter.load
    material = await loader(validated)
    return material.fields
""",
        """
def compose_credential_application(db, compatibility_mode):
    return decoy_application

def build_model_inference_policy(*args, **kwargs):
    return decoy_binding

async def endpoint(project_id, credential_id):
    composer = compose_credential_application
    builder = build_model_inference_policy
    application = composer(db, compatibility_mode=False)
    binding = builder(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validator = application.binding_service.validate_model_inference
    validated, resolution = await validator(binding)
    loader = application.material_adapter.load
    material = await loader(validated)
    return material.fields
""",
    ],
    ids=("receiver-method-aliases", "local-shadow-aliases"),
)
def test_ephemeral_endpoint_ast_guard_rejects_same_named_decoy_aliases(source: str) -> None:
    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == {
        "canonical_composition",
        "model_flow",
    }


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    binding = replacement_binding
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    return material.fields
""",
            {"model_flow", "canonical_composition"},
        ),
        (
            """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    validated = replacement_validated
    material = await application.material_adapter.load(validated)
    return material.fields
""",
            {"model_flow", "canonical_composition"},
        ),
        (
            """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=True)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    unrelated = compose_credential_application(db, compatibility_mode=False)
    return material.fields
""",
            {"canonical_composition"},
        ),
    ],
)
def test_ephemeral_endpoint_ast_guard_rejects_replaced_or_late_provenance(
    source: str,
    expected: set[str],
) -> None:
    violations = _ephemeral_endpoint_boundary_violations(source, require_flow=True)

    assert violations == expected


@pytest.mark.no_db
@pytest.mark.parametrize(
    "source",
    [
        """
async def endpoint(project_id, credential_id):
    first = compose_credential_application(db, compatibility_mode=False)
    second = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validator = first.binding_service.validate_model_inference
    loader = second.material_adapter.load
    validated, resolution = await validator(binding)
    material = await loader(validated)
    return material.fields
""",
        """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validator = application.binding_service.validate_model_inference
    validated, resolution = await validator(binding)
    application = compose_credential_application(db, compatibility_mode=False)
    loader = application.material_adapter.load
    material = await loader(validated)
    return material.fields
""",
    ],
)
def test_ephemeral_endpoint_ast_guard_rejects_mixed_application_aliases(source: str) -> None:
    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == {
        "canonical_composition",
        "model_flow",
    }


@pytest.mark.no_db
@pytest.mark.parametrize(
    "source",
    [
        """
def decoy_builder():
    return build_model_inference_policy(catalog, project_id="p", credential_id="c", engine_kind="codex", model_id=None)

async def decoy_validator(application, binding):
    return await application.binding_service.validate_model_inference(binding)

async def endpoint():
    application = compose_credential_application(db, compatibility_mode=False)
    material = await application.material_adapter.load(unvalidated)
    return material.fields
""",
        """
async def decoy(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    return material.fields

async def endpoint():
    application = compose_credential_application(db, compatibility_mode=False)
    material = await application.material_adapter.load(unvalidated)
    return material.fields
""",
        """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(other_binding)
    material = await application.material_adapter.load(validated)
    return material.fields
""",
        """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(other_validated)
    return material.fields
""",
        """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    decoy_material = await application.material_adapter.load(validated)
    material = await application.material_adapter.load(unvalidated)
    return material.fields
""",
    ],
)
def test_ephemeral_endpoint_ast_guard_rejects_decoy_or_disconnected_flow(source: str) -> None:
    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == {
        "canonical_composition",
        "model_flow",
    }


@pytest.mark.no_db
def test_ephemeral_endpoint_ast_guard_rejects_late_canonical_decoy_after_noncanonical_load() -> None:
    source = """
async def endpoint(project_id, credential_id):
    legacy_application = compose_credential_application(db, compatibility_mode=True)
    legacy_binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    legacy_validated, legacy_resolution = await legacy_application.binding_service.validate_model_inference(legacy_binding)
    legacy_material = await legacy_application.material_adapter.load(legacy_validated)

    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    return material.fields
"""

    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == {"canonical_composition"}


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    return material.fields
    unreachable = await application.material_adapter.load(unvalidated)
    return unreachable.fields
""",
            set(),
        ),
        (
            """
async def endpoint(project_id, credential_id):
    return None
    application = compose_credential_application(db, compatibility_mode=False)
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    return material.fields
""",
            {"canonical_composition", "model_flow"},
        ),
    ],
    ids=("unreachable-invalid-load", "unreachable-canonical-decoy"),
)
def test_ephemeral_endpoint_ast_guard_stops_paths_after_return(
    source: str,
    expected: set[str],
) -> None:
    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == expected


@pytest.mark.no_db
def test_ephemeral_endpoint_ast_guard_keeps_mutually_exclusive_branch_loads_independent() -> None:
    source = """
async def endpoint(project_id, credential_id, use_legacy):
    if use_legacy:
        application = compose_credential_application(db, compatibility_mode=True)
        binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
    else:
        application = compose_credential_application(db, compatibility_mode=False)
        binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
    return material.fields
"""

    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == {"canonical_composition"}


@pytest.mark.no_db
def test_ephemeral_endpoint_ast_guard_rejects_terminating_composition_flag_decoy() -> None:
    source = """
async def endpoint(project_id, credential_id, use_decoy):
    application = compose_credential_application(db, compatibility_mode=True)
    if use_decoy:
        application = compose_credential_application(db, compatibility_mode=False)
        return None
    binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
    validated, resolution = await application.binding_service.validate_model_inference(binding)
    material = await application.material_adapter.load(validated)
    return material.fields
"""

    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == {"canonical_composition"}


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    try:
        binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
    except Exception:
        raise
    return material.fields
""",
            set(),
        ),
        (
            """
async def endpoint(project_id, credential_id):
    try:
        application = compose_credential_application(db, compatibility_mode=True)
        binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
    except Exception:
        application = compose_credential_application(db, compatibility_mode=False)
        binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
    return material.fields
""",
            {"canonical_composition"},
        ),
        (
            """
async def endpoint(project_id, credential_id):
    application = compose_credential_application(db, compatibility_mode=False)
    try:
        binding = build_model_inference_policy(catalog, project_id=project_id, credential_id=credential_id, engine_kind="codex", model_id=None)
        validated, resolution = await application.binding_service.validate_model_inference(binding)
        material = await application.material_adapter.load(validated)
        return material.fields
    finally:
        unreachable = await application.material_adapter.load(unvalidated)
""",
            {"canonical_composition", "model_flow"},
        ),
    ],
    ids=("handler-shape", "except-branch-decoy", "finally-after-return"),
)
def test_ephemeral_endpoint_ast_guard_tracks_try_paths(
    source: str,
    expected: set[str],
) -> None:
    assert _ephemeral_endpoint_boundary_violations(source, require_flow=True) == expected


@pytest.mark.no_db
@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            """
async def bypass(credential_repository, credential_id):
    row = await credential_repository.get(credential_id)
    alias = row
    return alias.data
""",
            {"repository_call:get", "attribute:data"},
        ),
        (
            """
async def bypass(credentials, credential_id):
    resource = await credentials.get_resource(credential_id)
    alias = resource
    return alias.provider
""",
            {"repository_call:get_resource", "attribute:provider"},
        ),
        (
            """
async def bypass(credential_repository, credential_id):
    encrypted = await credential_repository.load_encrypted_material(credential_id)
    return encrypted.material
""",
            {"repository_call:load_encrypted_material", "attribute:material"},
        ),
        (
            """
async def bypass(application, validated):
    material = await application.material_adapter.load(validated)
    alias = material
    return alias.protocol
""",
            {"attribute:protocol"},
        ),
        (
            """
async def bypass(db, credential_id):
    service = CredentialService(db)
    row = await service.get(credential_id)
    return row.kind
""",
            {"call:CredentialService", "repository_call:get", "attribute:kind"},
        ),
        (
            """
async def bypass(credential_repository, credential_id):
    repo = credential_repository
    row = await repo.get(credential_id)
    return row.state
""",
            {"repository_call:get", "attribute:state"},
        ),
        (
            """
async def bypass(application, validated):
    loader = application.material_adapter
    material = await loader.load(validated)
    alias = material
    return alias.data
""",
            {"attribute:data"},
        ),
        (
            """
async def bypass(credential_repository, credential_id):
    return (await credential_repository.get(credential_id)).archived_at
""",
            {"repository_call:get", "attribute:archived_at"},
        ),
        (
            """
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService as Facade

async def bypass(db, credential_id):
    service = Facade(db)
    row = await service.get(credential_id)
    return row.deleted_at
            """,
            {
                "attribute:deleted_at",
                "call:CredentialService",
                "forbidden_import",
                "repository_call:get",
            },
        ),
        (
            """
async def bypass(credential_repository, credential_id):
    fetch = credential_repository.get
    row = await fetch(credential_id)
    return row.data
""",
            {"repository_call:get", "attribute:data"},
        ),
        (
            """
async def bypass(application, credential_id):
    repository = application.binding_service._repository
    fetch = repository.get
    row = await fetch(credential_id)
    return row.data
""",
            {"repository_call:get", "attribute:data"},
        ),
        (
            """
async def bypass(application, credential_id):
    repository = application.material_adapter._repository
    load = repository.load_encrypted_material
    encrypted = await load(credential_id)
    return encrypted.material
""",
            {"repository_call:load_encrypted_material", "attribute:material"},
        ),
        (
            """
async def bypass(service, credential_id):
    repository = service._credential_repository
    fetch = repository.get
    row = await fetch(credential_id)
    return row.state
""",
            {"repository_call:get", "attribute:state"},
        ),
        (
            """
async def bypass(holder, credential_id):
    repository = holder.credential_repository
    alias = repository
    row = await alias.get_resource(credential_id)
    return row.provider
""",
            {"repository_call:get_resource", "attribute:provider"},
        ),
        (
            """
def bypass(protector, ciphertext):
    unwrap = protector.reveal
    return unwrap(ciphertext)
""",
            {"call:reveal"},
        ),
        (
            """
def bypass(crypto, ciphertext):
    decryptor = crypto.decrypt
    return decryptor(ciphertext)
""",
            {"call:decrypt"},
        ),
        (
            """
def bypass(ciphertext):
    protector = LegacyV1MaterialProtector(key)
    unwrap = protector.reveal
    return unwrap(ciphertext)
""",
            {"call:LegacyV1MaterialProtector", "call:reveal"},
        ),
    ],
)
def test_ephemeral_endpoint_ast_guard_rejects_repository_and_alias_bypasses(
    source: str,
    expected: set[str],
) -> None:
    assert _ephemeral_endpoint_boundary_violations(source, require_flow=False) == expected
