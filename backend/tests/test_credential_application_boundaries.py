from __future__ import annotations

import ast
import uuid
from dataclasses import FrozenInstanceError, dataclass, field
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy import select

from app.joysafeter_api.api.v1.agent_identity_capture import _encrypt
from app.joysafeter_application.credentials import composition as credential_composition
from app.joysafeter_application.credentials.binding_service import (
    BindingIssuanceAuthority,
    CredentialBindingService,
    ValidatedCredentialBinding,
)
from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_application.credentials.ports import (
    CredentialAuditEntry,
    CredentialUnitOfWork,
)
from app.joysafeter_application.credentials.resource_service import CredentialResourceService
from app.joysafeter_application.credentials.snapshot_service import (
    CredentialSnapshotService,
    NoPersistentDependencyScanner,
)
from app.joysafeter_domain.credentials import (
    CredentialFieldName,
    CredentialGroupId,
    CredentialId,
    CredentialImpact,
    CredentialMaterial,
    CredentialUsage,
    DependencyDisposition,
    EngineKind,
    EnvironmentInjectionBinding,
    HttpEgressBinding,
    McpGroupBinding,
    ModelInferenceBinding,
    ProjectId,
    ReferenceSurfaceDescriptor,
    ReferenceSurfaceKind,
    ReferenceTarget,
    SensitiveValue,
)
from app.joysafeter_domain.credentials.bindings import EgressInjectKind, EgressInjectPolicy
from app.joysafeter_domain.credentials.dependencies import ReferenceScannerId, ReferenceSurfaceId
from app.joysafeter_domain.credentials.types import NormalizedEndpoint
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.model_inference_policy import build_model_inference_policy
from app.joysafeter_domain.models.joysafeter_credential import (
    JoySafeterCredential,
    JoySafeterCredentialGroup,
)
from app.joysafeter_domain.models.joysafeter_organization import Organization
from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox
from app.joysafeter_domain.models.joysafeter_security_audit_log import SecurityAuditLog
from app.joysafeter_domain.schemas.joysafeter_credential import (
    CreateCredentialGroupRequest,
    CreateCredentialRequest,
    UpdateCredentialRequest,
)
from app.joysafeter_domain.services.joysafeter_credential_service import CredentialService
from app.joysafeter_infrastructure.credentials.audit_adapter import (
    SqlAlchemyCredentialAuditAdapter,
)
from app.joysafeter_infrastructure.credentials.material_adapter import (
    ManagedCredentialMaterialAdapter,
)
from app.joysafeter_infrastructure.repository_access.material_adapter import (
    RepositoryAccessMaterialAdapter,
)
from app.joysafeter_infrastructure.sensitive_material.legacy_v1 import LegacyV1MaterialProtector
from app.joysafeter_infrastructure.task_identity.material_adapter import TaskIdentityMaterialAdapter

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
TEST_KEY = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def _transaction_ownership_violations(source: str) -> set[str]:
    tree = ast.parse(source)
    violations: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"commit", "rollback"}:
            violations.add(node.attr)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in {"commit", "rollback"}
        ):
            violations.add(str(node.args[1].value))
    return violations


def test_credential_transaction_ownership_is_application_only() -> None:
    paths = (
        APP_ROOT / "joysafeter_api/api/v1/credentials.py",
        APP_ROOT / "joysafeter_api/api/v1/credential_groups.py",
        APP_ROOT / "joysafeter_domain/services/joysafeter_credential_service.py",
        APP_ROOT / "joysafeter_domain/services/joysafeter_credential_group_service.py",
        APP_ROOT / "joysafeter_infrastructure/credentials/sqlalchemy_repository.py",
    )
    for path in paths:
        assert not _transaction_ownership_violations(path.read_text()), path


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("async def bypass(db):\n    await db.commit()\n", "commit"),
        ("async def bypass(db):\n    alias = db\n    await alias.rollback()\n", "rollback"),
        ("async def bypass(db):\n    finish = db.commit\n    await finish()\n", "commit"),
        ("def bypass(db, helper):\n    return helper(db.commit)\n", "commit"),
        ("async def bypass(ctx):\n    await ctx.session.commit()\n", "commit"),
        ("async def bypass(db):\n    await getattr(db, 'rollback')()\n", "rollback"),
    ),
)
def test_transaction_ownership_guard_rejects_alias_helper_and_attribute_bypasses(
    source: str,
    expected: str,
) -> None:
    assert expected in _transaction_ownership_violations(source)


def _calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    return called


def _credential_boundary_violations(source: str) -> set[str]:
    tree = ast.parse(source)
    forbidden_calls = {
        "CredentialCipher",
        "LegacyV1MaterialProtector",
        "decrypt",
        "get_credential_data",
        "reveal_values",
    }
    sensitive_attributes = {"kind", "material", "state"}
    scope_types = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    violations: set[str] = set()

    def call_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def dotted_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = dotted_name(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return None

    def scope_nodes(scope: ast.AST) -> list[ast.AST]:
        if isinstance(scope, ast.Lambda):
            pending = [scope.body]
        else:
            pending = list(getattr(scope, "body", ()))
        nodes: list[ast.AST] = []
        while pending:
            node = pending.pop()
            nodes.append(node)
            for child in ast.iter_child_nodes(node):
                if isinstance(child, scope_types):
                    continue
                pending.append(child)
        return nodes

    def target_names(node: ast.AST) -> set[str]:
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, (ast.List, ast.Tuple)):
            return {name for item in node.elts for name in target_names(item)}
        return set()

    def is_credential_source(node: ast.AST, aliases: set[str]) -> bool:
        if isinstance(node, (ast.Await, ast.Starred, ast.Yield, ast.YieldFrom)):
            return node.value is not None and is_credential_source(node.value, aliases)
        if isinstance(node, ast.Name):
            return node.id in aliases
        if isinstance(node, ast.Attribute):
            return is_credential_source(node.value, aliases)
        if isinstance(node, ast.Subscript):
            return is_credential_source(node.value, aliases)
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            return any(is_credential_source(item, aliases) for item in node.elts)
        if isinstance(node, ast.IfExp):
            return is_credential_source(node.body, aliases) or is_credential_source(node.orelse, aliases)
        if not isinstance(node, ast.Call):
            return False
        path = (dotted_name(node.func) or "").lower()
        leaf = call_name(node.func) or ""
        if ".credentials." in path or path.endswith(".credentials"):
            return True
        if "credential" in path and leaf.lower().startswith(
            ("create", "fetch", "find", "get", "load", "read", "resolve", "update")
        ):
            return True
        if "credential" in leaf.lower() and leaf.lower().startswith(
            ("fetch", "find", "get", "load", "read", "resolve")
        ):
            return True
        if leaf == "select" and any(isinstance(arg, ast.Name) and "credential" in arg.id.lower() for arg in node.args):
            return True
        if isinstance(node.func, ast.Attribute) and is_credential_source(node.func.value, aliases):
            return True
        return any(is_credential_source(arg, aliases) for arg in node.args)

    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        name = call_name(call.func)
        if name in forbidden_calls:
            violations.add(name)

    scopes = [tree, *(node for node in ast.walk(tree) if isinstance(node, scope_types[1:]))]
    for scope in scopes:
        nodes = scope_nodes(scope)
        aliases: set[str] = set()
        changed = True
        while changed:
            changed = False
            for node in nodes:
                assignments: list[tuple[ast.AST, ast.AST]] = []
                if isinstance(node, ast.Assign):
                    assignments.extend((target, node.value) for target in node.targets)
                elif isinstance(node, ast.AnnAssign) and node.value is not None:
                    assignments.append((node.target, node.value))
                elif isinstance(node, ast.NamedExpr):
                    assignments.append((node.target, node.value))
                elif isinstance(node, (ast.For, ast.AsyncFor)):
                    assignments.append((node.target, node.iter))
                for target, value in assignments:
                    if not is_credential_source(value, aliases):
                        continue
                    before = len(aliases)
                    aliases.update(target_names(target))
                    changed = changed or len(aliases) != before
        for node in nodes:
            if (
                isinstance(node, ast.Attribute)
                and node.attr in sensitive_attributes
                and is_credential_source(node.value, aliases)
            ):
                violations.add(node.attr)
    return violations


def test_legacy_credential_service_is_an_application_facade() -> None:
    path = APP_ROOT / "joysafeter_domain/services/joysafeter_credential_service.py"
    imports = _imports(path)

    assert not any(name.startswith("app.joysafeter_api") for name in imports)
    assert "app.joysafeter_domain.schemas.joysafeter_credential" not in imports
    assert "sqlalchemy" not in imports
    assert not any(name.startswith("sqlalchemy.") for name in imports)
    assert "app.joysafeter_application.credentials.composition" in imports


def test_repository_access_does_not_call_credential_service_encryption_helpers() -> None:
    path = APP_ROOT / "joysafeter_domain/services/joysafeter_session_resource_service.py"
    imports = _imports(path)
    calls = _calls(path)

    assert "app.joysafeter_domain.services.joysafeter_credential_service" not in imports
    assert "encrypt_data_for_storage" not in calls
    assert "app.joysafeter_application.credentials.composition" in imports


def test_task_identity_uses_its_purpose_specific_material_adapter() -> None:
    path = APP_ROOT / "joysafeter_api/api/v1/agent_identity_capture.py"
    imports = _imports(path)
    calls = _calls(path)

    assert "app.joysafeter_shared.security.credential_cipher" not in imports
    assert "CredentialCipher" not in calls
    assert "app.joysafeter_application.credentials.composition" in imports


def test_new_infrastructure_does_not_import_api_layer() -> None:
    for path in (APP_ROOT / "joysafeter_infrastructure").rglob("*.py"):
        assert not any(name.startswith("app.joysafeter_api") for name in _imports(path)), path


def test_persistent_consumers_have_ast_aware_credential_boundary_guards() -> None:
    paths = (
        APP_ROOT / "joysafeter_domain/services/joysafeter_agent_service.py",
        APP_ROOT / "joysafeter_domain/services/joysafeter_trigger_service.py",
        APP_ROOT / "joysafeter_domain/services/joysafeter_trigger_webhook_auth_service.py",
        APP_ROOT / "joysafeter_api/api/v1/environments.py",
        APP_ROOT / "joysafeter_domain/services/joysafeter_environment_service.py",
        APP_ROOT / "joysafeter_domain/services/joysafeter_session_service.py",
    )
    forbidden_imports = {
        "app.joysafeter_domain.services.joysafeter_credential_service",
        "app.joysafeter_domain.services.joysafeter_credential_group_service",
        "app.joysafeter_infrastructure.sensitive_material.legacy_v1",
    }
    for path in paths:
        assert not (_imports(path) & forbidden_imports), path
        assert not _credential_boundary_violations(path.read_text()), path


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("def bypass(payload):\n    return decrypt(payload)\n", "decrypt"),
        ("def bypass(helper, payload):\n    return helper.decrypt(payload)\n", "decrypt"),
        (
            "async def bypass(repo, credential_id):\n"
            "    row = await repo.credentials.get_resource(credential_id)\n"
            "    return row.kind\n",
            "kind",
        ),
        (
            "async def bypass(repo, credential_id):\n"
            "    row = await repo.load_credential(credential_id)\n"
            "    alias = row\n"
            "    return alias.material\n",
            "material",
        ),
        (
            "async def bypass(credential_repository, credential_id):\n"
            "    record = await credential_repository.get(credential_id)\n"
            "    alias = record\n"
            "    return alias.state\n",
            "state",
        ),
    ),
)
def test_persistent_consumer_ast_guard_rejects_bypass_fixtures(source: str, expected: str) -> None:
    assert expected in _credential_boundary_violations(source)


def test_persistent_consumer_ast_guard_allows_unrelated_state_fields() -> None:
    source = "def allowed(task, provider, document):\n    return task.state, provider.kind, document.material\n"

    assert not _credential_boundary_violations(source)


def test_purpose_material_adapters_import_only_neutral_legacy_protector() -> None:
    expected = "app.joysafeter_infrastructure.sensitive_material.legacy_v1"
    for relative_path in (
        "joysafeter_infrastructure/credentials/material_adapter.py",
        "joysafeter_infrastructure/task_identity/material_adapter.py",
        "joysafeter_infrastructure/repository_access/material_adapter.py",
    ):
        imports = _imports(APP_ROOT / relative_path)
        assert expected in imports
    assert "app.joysafeter_infrastructure.credentials.material_adapter" not in _imports(
        APP_ROOT / "joysafeter_infrastructure/task_identity/material_adapter.py"
    )
    assert "app.joysafeter_infrastructure.credentials.material_adapter" not in _imports(
        APP_ROOT / "joysafeter_infrastructure/repository_access/material_adapter.py"
    )


@dataclass
class _EncryptedMaterialRepository:
    fields: dict[str, str]
    load_count: int = 0

    async def load_encrypted_material(self, credential_id: CredentialId, project_id: ProjectId) -> dict[str, str]:
        self.load_count += 1
        return dict(self.fields)


@pytest.mark.asyncio
async def test_managed_material_adapter_returns_only_binding_authorized_fields(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="service",
            name="authorized-fields",
            data={"TOKEN": "allowed", "OTHER": "must-not-leak"},
        ),
        project_id=project_id,
    )
    binding = HttpEgressBinding(
        project_id=ProjectId(project_id),
        credential_id=CredentialId(str(credential.id)),
        endpoint=NormalizedEndpoint("https://example.com/api"),
        inject=EgressInjectPolicy(
            kind=EgressInjectKind.BEARER,
            credential_field=CredentialFieldName("TOKEN"),
        ),
    )

    validated = await application.binding_service.validate(binding)
    resolved = await application.material_adapter.load(validated)

    assert dict(resolved.fields) == {CredentialFieldName("TOKEN"): "allowed"}
    assert "must-not-leak" not in repr(resolved)


@pytest.mark.asyncio
async def test_environment_injection_is_the_only_binding_that_can_load_all_fields(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="service",
            name="environment-fields",
            data={"TOKEN": "one", "SECOND": "two"},
        ),
        project_id=project_id,
    )
    binding = EnvironmentInjectionBinding(
        project_id=ProjectId(project_id),
        credential_id=CredentialId(str(credential.id)),
    )

    validated = await application.binding_service.validate(binding)
    resolved = await application.material_adapter.load(validated)

    assert dict(resolved.fields) == {
        CredentialFieldName("TOKEN"): "one",
        CredentialFieldName("SECOND"): "two",
    }


def test_non_environment_binding_cannot_request_all_fields() -> None:
    binding = HttpEgressBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("credential-1"),
        endpoint=NormalizedEndpoint("https://example.com/api"),
        inject=EgressInjectPolicy(
            kind=EgressInjectKind.BEARER,
            credential_field=CredentialFieldName("TOKEN"),
        ),
    )

    with pytest.raises(ValueError, match="Environment Injection"):
        ValidatedCredentialBinding.all_fields(binding)


def test_model_validated_binding_cannot_be_caller_constructed_with_fields() -> None:
    binding = ModelInferenceBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("credential-1"),
        engine_kind=EngineKind.CODEX,
        model_id=None,
    )

    with pytest.raises(TypeError, match="dedicated model inference"):
        ValidatedCredentialBinding(
            binding=binding,
            authorized_fields=frozenset({CredentialFieldName("UNRELATED_SECRET")}),
        )

    assert not hasattr(ValidatedCredentialBinding, "_model_inference")


@pytest.mark.asyncio
async def test_material_adapter_rejects_forged_model_validation_before_repository_load() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    repository = _EncryptedMaterialRepository({"UNRELATED_SECRET": protector.protect("must-not-load")})
    adapter = ManagedCredentialMaterialAdapter(repository, protector, BindingIssuanceAuthority())
    binding = ModelInferenceBinding(
        project_id=ProjectId("project-1"),
        credential_id=CredentialId("credential-1"),
        engine_kind=EngineKind.CODEX,
        model_id=None,
    )
    forged = object.__new__(ValidatedCredentialBinding)
    object.__setattr__(forged, "binding", binding)
    object.__setattr__(
        forged,
        "authorized_fields",
        frozenset({CredentialFieldName("UNRELATED_SECRET")}),
    )
    object.__setattr__(forged, "requests_all_fields", False)

    with pytest.raises(TypeError, match="not issued"):
        await adapter.load(forged)

    assert repository.load_count == 0


def test_purpose_specific_adapters_share_only_legacy_v1_protector() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    identity = TaskIdentityMaterialAdapter(protector)
    repository = RepositoryAccessMaterialAdapter(protector)

    identity_ciphertext = identity.protect_identity_credential("identity-value")
    repository_ciphertext = repository.protect_repository_token("repository-value")

    assert identity_ciphertext.startswith("enc:v1:")
    assert repository_ciphertext.startswith("enc:v1:")
    assert identity.reveal_identity_credential(identity_ciphertext) == "identity-value"
    assert repository.reveal_repository_token(repository_ciphertext) == "repository-value"

    identity_imports = _imports(APP_ROOT / "joysafeter_infrastructure/task_identity/material_adapter.py")
    repository_imports = _imports(APP_ROOT / "joysafeter_infrastructure/repository_access/material_adapter.py")
    assert not any(name.startswith("app.joysafeter_application") for name in identity_imports)
    assert not any(name.startswith("app.joysafeter_application") for name in repository_imports)


@dataclass
class _FakeCredentialRepository:
    result: Any = object()
    error: Exception | None = None

    async def create(self, request: Any, project_id: str) -> Any:
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class _FakeGroupRepository:
    pass


@dataclass
class _FakeAudit:
    entries: list[CredentialAuditEntry] = field(default_factory=list)

    async def append(self, entry: CredentialAuditEntry) -> None:
        self.entries.append(entry)


@dataclass
class _CapturingDb:
    added: list[Any] = field(default_factory=list)

    def add(self, value: Any) -> None:
        self.added.append(value)


@pytest.mark.asyncio
async def test_audit_adapter_target_type_cannot_be_overridden_by_details() -> None:
    db = _CapturingDb()
    adapter = SqlAlchemyCredentialAuditAdapter(db)

    await adapter.append(
        CredentialAuditEntry(
            action="environment.credentials.updated",
            project_id="project-1",
            target_type="environment",
            target_id="environment-1",
            details={"target_type": "credential"},
        )
    )

    assert db.added[0].details["target_type"] == "environment"


@dataclass
class _FakeImpacts:
    pending: list[CredentialImpact] = field(default_factory=list)

    async def mark_pending(self, impact: CredentialImpact) -> CredentialImpact:
        self.pending.append(impact)
        return impact

    async def nudge_after_commit(self) -> None:
        return None


@dataclass
class _FakeUnitOfWork:
    credentials: _FakeCredentialRepository
    groups: _FakeGroupRepository = field(default_factory=_FakeGroupRepository)
    audit: _FakeAudit = field(default_factory=_FakeAudit)
    impacts: _FakeImpacts = field(default_factory=_FakeImpacts)
    commits: int = 0
    rollbacks: int = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def test_unit_of_work_protocol_exposes_transaction_collaborators() -> None:
    annotations = CredentialUnitOfWork.__annotations__
    assert set(("credentials", "groups", "audit", "impacts")) <= set(annotations)
    assert callable(getattr(CredentialUnitOfWork, "commit"))
    assert callable(getattr(CredentialUnitOfWork, "rollback"))


@pytest.mark.asyncio
async def test_application_service_commits_mutation_and_audit_together() -> None:
    result = object()
    uow = _FakeUnitOfWork(credentials=_FakeCredentialRepository(result=result))
    service = CredentialResourceService(uow)

    assert await service.create(object(), project_id="project-1") is result
    assert uow.commits == 1
    assert uow.rollbacks == 0
    assert [entry.action for entry in uow.audit.entries] == ["credential.created"]


@pytest.mark.asyncio
async def test_application_service_rolls_back_repository_failure() -> None:
    uow = _FakeUnitOfWork(credentials=_FakeCredentialRepository(error=RuntimeError("write failed")))
    service = CredentialResourceService(uow)

    with pytest.raises(RuntimeError, match="write failed"):
        await service.create(object(), project_id="project-1")

    assert uow.commits == 0
    assert uow.rollbacks == 1
    assert uow.audit.entries == []


def test_managed_adapter_is_the_only_importer_of_domain_reveal_seam() -> None:
    importers: list[Path] = []
    for path in APP_ROOT.rglob("*.py"):
        if path == APP_ROOT / "joysafeter_domain/credentials/material.py":
            continue
        if "_issue_material_reveal_capability" in path.read_text():
            importers.append(path.relative_to(APP_ROOT))

    assert importers == [Path("joysafeter_infrastructure/credentials/material_adapter.py")]


def test_managed_adapter_protects_domain_material_without_exposing_reveal_capability() -> None:
    protector = LegacyV1MaterialProtector(TEST_KEY)
    adapter = ManagedCredentialMaterialAdapter(
        _EncryptedMaterialRepository({}),
        protector,
        BindingIssuanceAuthority(),
    )
    material = CredentialMaterial({CredentialFieldName("TOKEN"): SensitiveValue("managed-value")})

    protected = adapter.protect(material)

    assert protected["TOKEN"].startswith("enc:v1:")
    assert protector.reveal(protected["TOKEN"]) == "managed-value"


async def _make_project(db_session) -> str:
    org = Organization(name=f"org-{uuid.uuid4()}", slug=f"org-{uuid.uuid4()}")
    db_session.add(org)
    await db_session.flush()
    project = Project(org_id=org.id, name=f"project-{uuid.uuid4()}", slug=f"project-{uuid.uuid4()}")
    db_session.add(project)
    await db_session.commit()
    return project.id


@pytest.mark.asyncio
async def test_production_composition_binding_service_maps_sqlalchemy_resource(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="composed-model",
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    binding = build_model_inference_policy(
        get_llm_catalog(),
        project_id=project_id,
        credential_id=credential.id,
        engine_kind=EngineKind.CODEX,
        model_id="gpt-test",
    )

    validated, resolution = await application.binding_service.validate_model_inference(binding)

    assert validated.binding is binding
    assert validated.authorized_fields == frozenset({CredentialFieldName("OPENAI_API_KEY")})
    assert resolution.credential_profile_id == "openai_bearer"


def test_canonical_composition_owns_catalog_and_shared_issuance_authority(db_session) -> None:
    application = compose_credential_application(db_session)

    assert application.binding_service._catalog is get_llm_catalog()
    assert application.binding_service._issuance_authority is application.material_adapter._issuance_authority
    assert not any(
        marker in name.lower()
        for name in dir(application.binding_service._issuance_authority)
        for marker in ("register", "issue", "add")
    )
    assert not any(
        marker in name.lower() for name in dir(application.binding_service) for marker in ("register", "issue")
    )


def test_binding_service_rejects_real_caller_supplied_catalog() -> None:
    forged_catalog = get_llm_catalog().model_copy(deep=True)

    with pytest.raises(TypeError, match="BindingIssuanceAuthority"):
        CredentialBindingService(_FakeCredentialRepository(), forged_catalog)


def test_composition_cannot_substitute_catalog_for_binding_service() -> None:
    source = (APP_ROOT / "joysafeter_application/credentials/composition.py").read_text()

    assert "CredentialBindingService(repository, get_llm_catalog())" not in source
    assert "CredentialBindingService(repository, issuance_authority)" in source


@pytest.mark.asyncio
async def test_generic_binding_validation_rejects_model_inference(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="generic-model-path",
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    binding = ModelInferenceBinding(
        project_id=ProjectId(project_id),
        credential_id=CredentialId(str(credential.id)),
        engine_kind=EngineKind.CODEX,
        model_id=None,
    )

    with pytest.raises(TypeError, match="dedicated model inference"):
        await application.binding_service.validate(binding)

    with pytest.raises(TypeError, match="requested_fields"):
        await application.binding_service.validate(
            binding,
            requested_fields=frozenset({CredentialFieldName("UNRELATED_SECRET")}),
        )


@pytest.mark.asyncio
async def test_tampered_validated_model_binding_cannot_reach_material_repository(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="tamper-model",
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    binding = build_model_inference_policy(
        get_llm_catalog(),
        project_id=project_id,
        credential_id=credential.id,
        engine_kind=EngineKind.CODEX,
        model_id=None,
    )
    validated, _resolution = await application.binding_service.validate_model_inference(binding)
    object.__setattr__(
        validated,
        "authorized_fields",
        frozenset({CredentialFieldName("UNRELATED_SECRET")}),
    )
    load_count = 0
    repository = application.material_adapter._repository
    original_load = repository.load_encrypted_material

    async def observe_load(credential_id, scoped_project_id):
        nonlocal load_count
        load_count += 1
        return await original_load(credential_id, scoped_project_id)

    repository.load_encrypted_material = observe_load

    with pytest.raises(TypeError, match="mutated"):
        await application.material_adapter.load(validated)

    assert load_count == 0

    with pytest.raises(TypeError, match="dedicated model inference"):
        await application.binding_service.validate_reference(binding)


@pytest.mark.asyncio
async def test_copied_validated_binding_identity_cannot_reach_material_repository(db_session) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="copied-model-binding",
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    binding = build_model_inference_policy(
        get_llm_catalog(),
        project_id=project_id,
        credential_id=credential.id,
        engine_kind=EngineKind.CODEX,
        model_id=None,
    )
    validated, _resolution = await application.binding_service.validate_model_inference(binding)
    copied = object.__new__(ValidatedCredentialBinding)
    for name in (
        "binding",
        "authorized_fields",
        "requests_all_fields",
        "_model_validation_seal",
        "_integrity",
    ):
        if hasattr(validated, name):
            object.__setattr__(copied, name, getattr(validated, name))
    load_count = 0
    repository = application.material_adapter._repository
    original_load = repository.load_encrypted_material

    async def observe_load(credential_id, scoped_project_id):
        nonlocal load_count
        load_count += 1
        return await original_load(credential_id, scoped_project_id)

    repository.load_encrypted_material = observe_load

    with pytest.raises(TypeError, match="not issued"):
        await application.material_adapter.load(copied)

    assert load_count == 0


@pytest.mark.asyncio
async def test_validated_binding_is_frozen_and_cannot_cross_compositions(db_session) -> None:
    project_id = await _make_project(db_session)
    issuing_application = compose_credential_application(db_session)
    other_application = compose_credential_application(db_session)
    credential = await issuing_application.resource_service.create(
        CreateCredentialRequest(
            kind="model",
            name="cross-composition-model",
            provider="openai",
            protocol="openai_responses",
            data={"OPENAI_API_KEY": "secret"},
        ),
        project_id=project_id,
    )
    binding = build_model_inference_policy(
        get_llm_catalog(),
        project_id=project_id,
        credential_id=credential.id,
        engine_kind=EngineKind.CODEX,
        model_id=None,
    )
    validated, _resolution = await issuing_application.binding_service.validate_model_inference(binding)

    with pytest.raises(FrozenInstanceError):
        validated.authorized_fields = frozenset({CredentialFieldName("UNRELATED_SECRET")})

    with pytest.raises(TypeError, match="not issued"):
        await other_application.material_adapter.load(validated)


def test_binding_service_module_has_no_reproducible_model_seal_recipe() -> None:
    from app.joysafeter_application.credentials import binding_service

    assert not hasattr(binding_service, "_MODEL_VALIDATION_SEAL")
    assert not hasattr(binding_service, "_validation_integrity")


@pytest.mark.asyncio
async def test_production_composition_group_service_maps_groups_and_members(db_session) -> None:
    project_id = await _make_project(db_session)
    protector = LegacyV1MaterialProtector(TEST_KEY)
    group = JoySafeterCredentialGroup(project_id=project_id, name="composed-group")
    db_session.add(group)
    await db_session.flush()
    member = JoySafeterCredential(
        project_id=project_id,
        kind="mcp",
        name="member",
        data={"token_value": protector.protect("token")},
        credential_type="static_bearer",
        group_id=group.id,
        mcp_server_url="https://mcp.example.com",
        normalized_mcp_server_url="https://mcp.example.com",
    )
    db_session.add(member)
    await db_session.commit()
    application = compose_credential_application(db_session)
    binding = McpGroupBinding(
        project_id=ProjectId(project_id),
        group_ids=(CredentialGroupId(str(group.id)),),
        declared_server_urls=(),
    )

    await application.group_service.validate_binding(binding)


@pytest.mark.asyncio
async def test_production_composition_orders_mutation_audit_impact_commit_nudge(
    db_session,
    monkeypatch,
) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="ordered", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    sandbox = JoySafeterSandbox(
        project_id=project_id,
        image="test-image:latest",
        status="running",
        networking_status="ready",
        config={"fingerprint": {"networking": {"type": "limited"}}},
    )
    db_session.add(sandbox)
    await db_session.commit()
    credential_id = credential.id
    sandbox_id = sandbox.id
    events: list[str] = []
    resolved_impacts: list[CredentialImpact] = []

    original_update = application.uow.credentials.update
    original_append = application.uow.audit.append
    original_mark = application.uow.impacts.mark_pending

    async def recorded_update(*args, **kwargs):
        events.append("mutation")
        return await original_update(*args, **kwargs)

    async def recorded_append(entry):
        events.append("audit")
        await original_append(entry)

    async def recorded_mark(impact):
        events.append("impact")
        resolved = await original_mark(impact)
        resolved_impacts.append(resolved)
        return resolved

    async def recorded_nudge():
        events.append("nudge")

    monkeypatch.setattr(application.uow.credentials, "update", recorded_update)
    monkeypatch.setattr(application.uow.audit, "append", recorded_append)
    monkeypatch.setattr(application.uow.impacts, "mark_pending", recorded_mark)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", recorded_nudge)
    sqlalchemy_event.listen(db_session.sync_session, "after_commit", lambda session: events.append("commit"))

    await application.resource_service.update(
        credential_id,
        UpdateCredentialRequest(data={"TOKEN": "new"}),
        project_id=project_id,
    )

    assert events == ["mutation", "audit", "impact", "commit", "nudge"]
    assert len(resolved_impacts) == 1
    impact = resolved_impacts[0]
    assert impact.usage is CredentialUsage.HTTP_EGRESS
    assert impact.source == "credential"
    assert impact.project_id == ProjectId(project_id)
    assert impact.affected_sandbox_ids == frozenset({str(sandbox_id)})
    assert impact.affected_session_ids == frozenset()
    assert impact.dispositions == frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY})
    assert (
        await db_session.execute(select(JoySafeterSandbox.networking_status).where(JoySafeterSandbox.id == sandbox_id))
    ).scalar_one() == "pending"
    audit_rows = (
        (
            await db_session.execute(
                select(SecurityAuditLog).where(
                    SecurityAuditLog.event_type == "credential.updated",
                    SecurityAuditLog.details["project_id"].astext == project_id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(audit_rows) == 1


@pytest.mark.asyncio
async def test_production_composition_rolls_back_unconditionally_before_commit(
    db_session,
    monkeypatch,
) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="rollback-original", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    credential_id = credential.id
    events: list[str] = []
    original_update = application.uow.credentials.update

    async def recorded_update(*args, **kwargs):
        events.append("mutation")
        return await original_update(*args, **kwargs)

    async def failing_audit(entry):
        events.append("audit")
        raise RuntimeError("audit failed")

    monkeypatch.setattr(application.uow.credentials, "update", recorded_update)
    monkeypatch.setattr(application.uow.audit, "append", failing_audit)
    sqlalchemy_event.listen(db_session.sync_session, "after_rollback", lambda session: events.append("rollback"))

    with pytest.raises(RuntimeError, match="audit failed"):
        await application.resource_service.update(
            credential_id,
            UpdateCredentialRequest(name="rollback-changed"),
            project_id=project_id,
        )

    assert events == ["mutation", "audit", "rollback"]
    persisted_name = (
        await db_session.execute(select(JoySafeterCredential.name).where(JoySafeterCredential.id == credential_id))
    ).scalar_one()
    assert persisted_name == "rollback-original"


@pytest.mark.asyncio
async def test_post_commit_nudge_failure_is_best_effort(db_session, monkeypatch) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="nudge", data={"TOKEN": "old"}),
        project_id=project_id,
    )

    async def failing_nudge():
        raise RuntimeError("relay unavailable")

    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", failing_nudge)

    updated = await application.resource_service.update(
        credential.id,
        UpdateCredentialRequest(name="nudge-updated"),
        project_id=project_id,
    )

    assert updated.name == "nudge-updated"


@pytest.mark.asyncio
async def test_idempotent_resource_and_group_lifecycle_skip_transition_audit_and_nudge(
    db_session,
    monkeypatch,
) -> None:
    project_id = await _make_project(db_session)
    application = compose_credential_application(db_session)
    credential = await application.resource_service.create(
        CreateCredentialRequest(kind="service", name="idempotent-audit", data={"TOKEN": "old"}),
        project_id=project_id,
    )
    group = await application.group_service.create(
        CreateCredentialGroupRequest(name="idempotent-audit-group"),
        project_id=project_id,
    )
    audit_actions: list[str] = []
    nudge_calls = 0
    original_append = application.uow.audit.append

    async def record_audit(entry):
        audit_actions.append(entry.action)
        await original_append(entry)

    async def record_nudge():
        nonlocal nudge_calls
        nudge_calls += 1

    monkeypatch.setattr(application.uow.audit, "append", record_audit)
    monkeypatch.setattr(application.uow.impacts, "nudge_after_commit", record_nudge)

    resource_operations = (
        application.resource_service.archive,
        application.resource_service.restore,
        application.resource_service.soft_delete,
    )
    group_operations = (
        application.group_service.archive,
        application.group_service.restore,
        application.group_service.soft_delete,
    )
    for operation in resource_operations:
        await operation(credential.id, project_id=project_id)
        expected_audits = len(audit_actions)
        expected_nudges = nudge_calls
        await operation(credential.id, project_id=project_id)
        assert len(audit_actions) == expected_audits
        assert nudge_calls == expected_nudges
    for operation in group_operations:
        await operation(group.id, project_id=project_id)
        expected_audits = len(audit_actions)
        expected_nudges = nudge_calls
        await operation(group.id, project_id=project_id)
        assert len(audit_actions) == expected_audits
        assert nudge_calls == expected_nudges

    assert audit_actions == [
        "credential.archived",
        "credential.restored",
        "credential.deleted",
        "credential_group.archived",
        "credential_group.restored",
        "credential_group.deleted",
    ]
    assert nudge_calls == 6


def test_credential_impact_is_authoritative_typed_contract() -> None:
    impact = CredentialImpact(
        usage=CredentialUsage.HTTP_EGRESS,
        source="credential",
        project_id=ProjectId("project-1"),
        affected_sandbox_ids=frozenset({"sandbox-1"}),
        affected_session_ids=frozenset({"session-1"}),
        dispositions=frozenset({DependencyDisposition.REFRESH_RUNTIME_POLICY}),
    )

    assert impact.usage is CredentialUsage.HTTP_EGRESS
    assert impact.source == "credential"
    assert impact.project_id == ProjectId("project-1")


def test_task_identity_blank_material_is_not_misclassified_as_key_error() -> None:
    with pytest.raises(ValueError, match="identity credential must be non-empty"):
        _encrypt("", TEST_KEY)


def test_credential_facade_getattr_is_safe_before_initialization() -> None:
    facade = CredentialService.__new__(CredentialService)

    with pytest.raises(AttributeError, match="missing"):
        getattr(facade, "missing")


@dataclass(frozen=True)
class _Scanner:
    scanner_id: ReferenceScannerId

    async def scan_resource(self, project_id, credential_id):
        return ()


def _persistent_descriptor(scanner_id: str) -> ReferenceSurfaceDescriptor:
    return ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId(f"surface-{scanner_id}"),
        kind=ReferenceSurfaceKind.LIVE_BINDING,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.BLOCK_RESOURCE_ARCHIVE}),
        scanner_id=ReferenceScannerId(scanner_id),
        owner="test",
        persistent=True,
    )


def _ephemeral_descriptor(scanner_id: str) -> ReferenceSurfaceDescriptor:
    return ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId(f"surface-{scanner_id}"),
        kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        scanner_id=ReferenceScannerId(scanner_id),
        owner="test",
        persistent=False,
    )


def test_scanner_registry_rejects_duplicate_scanners() -> None:
    scanner_id = ReferenceScannerId("scanner-1")
    service = CredentialSnapshotService(
        descriptors=(_persistent_descriptor("scanner-1"),),
        scanners=(_Scanner(scanner_id), _Scanner(scanner_id)),
    )

    with pytest.raises(ValueError, match="duplicate"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_missing_persistent_scanner() -> None:
    service = CredentialSnapshotService(descriptors=(_persistent_descriptor("scanner-1"),))

    with pytest.raises(ValueError, match="missing"):
        service.validate_scanner_registration()


def test_scanner_registry_accepts_explicit_no_persistent_scanner() -> None:
    scanner_id = ReferenceScannerId("ephemeral-scanner")
    service = CredentialSnapshotService(
        descriptors=(_ephemeral_descriptor(str(scanner_id)),),
        scanners=(NoPersistentDependencyScanner(scanner_id),),
    )

    service.validate_scanner_registration()

    assert service.scanner(scanner_id).reason == "ephemeral_consumer"


def test_scanner_registry_rejects_missing_ephemeral_scanner() -> None:
    service = CredentialSnapshotService(descriptors=(_ephemeral_descriptor("ephemeral-scanner"),))

    with pytest.raises(ValueError, match="missing"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_descriptor_without_scanner_metadata() -> None:
    descriptor = ReferenceSurfaceDescriptor(
        surface_id=ReferenceSurfaceId("ephemeral-surface"),
        kind=ReferenceSurfaceKind.EPHEMERAL_CONSUMER,
        target=ReferenceTarget.RESOURCE,
        dispositions=frozenset({DependencyDisposition.AUDIT_ONLY}),
        scanner_id=None,
        owner="test",
        persistent=False,
    )
    service = CredentialSnapshotService(descriptors=(descriptor,))

    with pytest.raises(ValueError, match="descriptors_without_scanners"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_concrete_ephemeral_scanner() -> None:
    scanner_id = ReferenceScannerId("ephemeral-scanner")
    service = CredentialSnapshotService(
        descriptors=(_ephemeral_descriptor(str(scanner_id)),),
        scanners=(_Scanner(scanner_id),),
    )

    with pytest.raises(ValueError, match="wrong_scanner_kinds"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_no_persistent_scanner_for_persistent_descriptor() -> None:
    scanner_id = ReferenceScannerId("persistent-scanner")
    service = CredentialSnapshotService(
        descriptors=(_persistent_descriptor(str(scanner_id)),),
        scanners=(NoPersistentDependencyScanner(scanner_id),),
    )

    with pytest.raises(ValueError, match="wrong_scanner_kinds"):
        service.validate_scanner_registration()


def test_scanner_registry_rejects_unknown_scanner() -> None:
    service = CredentialSnapshotService(
        descriptors=(_ephemeral_descriptor("ephemeral-scanner"),),
        scanners=(NoPersistentDependencyScanner(ReferenceScannerId("unknown-scanner")),),
    )

    with pytest.raises(ValueError, match="extra"):
        service.validate_scanner_registration()


@pytest.mark.parametrize("registration", ["missing", "duplicate", "wrong_kind"])
def test_canonical_composition_rejects_invalid_ephemeral_registration(
    db_session,
    monkeypatch,
    registration: str,
) -> None:
    scanner_id = ReferenceScannerId("ephemeral-scanner")
    descriptor = _ephemeral_descriptor(str(scanner_id))
    scanners = {
        "missing": (),
        "duplicate": (
            NoPersistentDependencyScanner(scanner_id),
            NoPersistentDependencyScanner(scanner_id),
        ),
        "wrong_kind": (_Scanner(scanner_id),),
    }[registration]
    monkeypatch.setattr(
        credential_composition,
        "_task5_snapshot_registry",
        lambda: ((descriptor,), scanners),
        raising=False,
    )

    with pytest.raises(ValueError, match="credential scanner registry mismatch"):
        compose_credential_application(db_session)


def test_canonical_composition_registers_validated_dependency_scanners(db_session) -> None:
    application = compose_credential_application(db_session)

    assert application.snapshot_service.descriptors
    application.snapshot_service.validate_scanner_registration()
    for descriptor in application.snapshot_service.descriptors:
        scanner = application.snapshot_service.scanner(descriptor.scanner_id)
        assert descriptor.persistent is not isinstance(scanner, NoPersistentDependencyScanner)
