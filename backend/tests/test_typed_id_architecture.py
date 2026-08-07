import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db


BACKEND_ROOT = Path(__file__).resolve().parents[1]

CORE_TYPED_ID_FILES = (
    "app/joysafeter_api/api/v1/agents.py",
    "app/joysafeter_api/api/v1/analytics.py",
    "app/joysafeter_api/api/v1/environments.py",
    "app/joysafeter_api/api/v1/files.py",
    "app/joysafeter_api/api/v1/secrets.py",
    "app/joysafeter_api/api/v1/sandboxes.py",
    "app/joysafeter_api/api/v1/sessions.py",
    "app/joysafeter_api/api/v1/tasks.py",
    "app/joysafeter_api/api/v1/triggers.py",
    "app/joysafeter_api/api/v1/vaults.py",
    "app/joysafeter_domain/services/agent_trigger_execution.py",
    "app/joysafeter_domain/services/analytics_service.py",
    "app/joysafeter_domain/services/joysafeter_agent_service.py",
    "app/joysafeter_domain/services/joysafeter_file_service.py",
    "app/joysafeter_domain/services/joysafeter_sandbox_service.py",
    "app/joysafeter_domain/services/joysafeter_secret_service.py",
    "app/joysafeter_domain/services/joysafeter_session_resource_service.py",
    "app/joysafeter_domain/services/joysafeter_session_service.py",
    "app/joysafeter_domain/services/joysafeter_task_service.py",
    "app/joysafeter_domain/services/joysafeter_task_state_machine.py",
    "app/joysafeter_domain/services/joysafeter_trigger_fire_service.py",
    "app/joysafeter_domain/services/joysafeter_trigger_runtime_gate.py",
    "app/joysafeter_domain/services/joysafeter_trigger_service.py",
    "app/joysafeter_domain/services/joysafeter_vault_service.py",
    "app/joysafeter_domain/services/task_submission_service.py",
)

SKILL_TYPED_ID_FILES = (
    "app/joysafeter_api/api/v1/skills.py",
    "app/joysafeter_api/api/v1/skills_ai_authoring.py",
    "app/joysafeter_domain/repositories/joysafeter_skill.py",
    "app/joysafeter_domain/repositories/joysafeter_skill_version.py",
    "app/joysafeter_domain/services/joysafeter_skill_security.py",
    "app/joysafeter_domain/services/joysafeter_skill_service.py",
)

STORAGE_TYPED_ID_FILES = (
    "app/joysafeter_api/api/v1/storage_volumes.py",
    "app/joysafeter_domain/schemas/joysafeter_storage_mount.py",
    "app/joysafeter_domain/schemas/joysafeter_session.py",
    "app/joysafeter_domain/services/joysafeter_storage_mount_service.py",
)


@pytest.mark.parametrize("relative_path", CORE_TYPED_ID_FILES)
def test_core_execution_graph_has_no_bare_uuid_entity_annotations(relative_path: str):
    source = (BACKEND_ROOT / relative_path).read_text()
    forbidden = re.compile(
        r"\b(agent_id|session_id|task_id|sandbox_id|trigger_id|environment_id|env_id|secret_id|vault_id|cred_id|credential_id|file_id|resource_id|event_id)\s*:\s*(?:Optional\[)?uuid\.UUID"
    )

    assert forbidden.search(source) is None, relative_path


def test_agent_legacy_helpers_are_removed_from_application_code():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        source = path.read_text()
        if "parse_agent_id" in source or "format_agent_id" in source:
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_python_application_has_no_bare_core_entity_annotations():
    app_root = BACKEND_ROOT / "app"
    forbidden = re.compile(
        r"\b(?P<field>(?:(?:[A-Za-z0-9]+_)?(?:agent|session|task|sandbox|trigger|environment|secret|vault|credential|memory_store|memory|memory_version|file|session_resource|event|storage_volume|storage_grant|storage_mount_audit|volume)_id|store_id|env_id|cred_id|resource_id))\s*:\s*"
        r"(?:(?:Optional|Union)\[)?(?:uuid\.UUID|UUID|str|Any)"
    )
    matches = []
    for path in app_root.rglob("*.py"):
        relative_path = str(path.relative_to(BACKEND_ROOT))
        violations = [
            match.group("field")
            for match in forbidden.finditer(path.read_text())
            if match.group("field") not in {"harness_session_id", "source_event_id"}
            and not (
                relative_path == "app/joysafeter_domain/schemas/joysafeter_session.py"
                and match.group("field") == "environment_id"
            )
        ]
        if violations:
            matches.append(relative_path)

    assert matches == []


def test_core_legacy_formatters_are_removed():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        source = path.read_text()
        if "format_session_id" in source or "format_task_id" in source or "format_sandbox_id" in source:
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_core_legacy_parsers_are_removed():
    app_root = BACKEND_ROOT / "app"
    forbidden = (
        "parse_agent_id",
        "parse_session_id",
        "parse_task_id",
        "parse_task_after_id",
        "parse_sandbox_id",
        "parse_trigger_id",
        "parse_env_id",
        "parse_secret_id",
        "parse_vault_id",
        "parse_cred_id",
        "parse_skill_id",
        "parse_skill_file_id",
        "parse_skill_security_scan_id",
        "parse_file_id",
        "parse_resource_id",
        "parse_event_id",
    )
    matches = []
    for path in app_root.rglob("*.py"):
        source = path.read_text()
        if any(name in source for name in forbidden):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


@pytest.mark.parametrize("relative_path", SKILL_TYPED_ID_FILES)
def test_skill_execution_graph_has_no_bare_uuid_entity_annotations(relative_path: str):
    source = (BACKEND_ROOT / relative_path).read_text()
    forbidden = re.compile(
        r"\b(skill_id|file_id|scan_id|version_id)\s*:\s*(?:Optional\[)?(?:uuid\.UUID|UUID|str|Any)"
    )

    assert forbidden.search(source) is None, relative_path


@pytest.mark.parametrize("relative_path", STORAGE_TYPED_ID_FILES)
def test_storage_execution_graph_has_no_bare_identity_annotations(relative_path: str):
    source = (BACKEND_ROOT / relative_path).read_text()
    forbidden = re.compile(r"\b(volume_id|after_id)\s*:\s*(?:Optional\[)?(?:uuid\.UUID|UUID|str|Any)")

    assert forbidden.search(source) is None, relative_path


def test_same_id_compatibility_helper_is_removed():
    app_root = BACKEND_ROOT / "app"
    matches = []
    for path in app_root.rglob("*.py"):
        if "same_id" in path.read_text():
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_python_application_has_no_direct_concrete_entity_id_construction():
    app_root = BACKEND_ROOT / "app"
    id_module = app_root / "joysafeter_shared/ids.py"
    direct_constructor = re.compile(
        r"\b(?:AgentId|SessionId|TaskId|EnvironmentId|SecretId|TriggerId|MemoryStoreId|MemoryId|MemoryVersionId|SandboxId|VaultId|CredentialId|SkillId|SkillFileId|SkillSecurityScanId|SkillVersionId|SkillVersionFileId|SkillUsageId|EventId|FileId|SessionResourceId|StorageVolumeId|StorageGrantId|StorageMountAuditId)\s*\("
    )
    matches = []
    for path in app_root.rglob("*.py"):
        if path == id_module:
            continue
        if direct_constructor.search(path.read_text()):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_python_application_does_not_reprefix_typed_entity_rows():
    app_root = BACKEND_ROOT / "app"
    forbidden = re.compile(
        r"f[\"'](?:agent_|sess_|task_|sbx_|trig_|env_|secret_|vault_|cred_|file_|sesrsc_|evt_|vol_|stgrant_|staudit_)\{[^}]+\.id\}"
    )
    matches = []
    for path in app_root.rglob("*.py"):
        if forbidden.search(path.read_text()):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_analytics_schemas_keep_agent_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/analytics.py").read_text()

    assert re.search(r"class AgentMetricsResponse.*?agent_id:\s*AgentId", source, re.S)
    assert re.search(r"class AlertItem.*?agent_id:\s*Optional\[AgentId\]", source, re.S)
    assert re.search(r"class AgentRankingItem.*?agent_id:\s*AgentId", source, re.S)


def test_trigger_models_keep_trigger_identity_typed():
    trigger_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_trigger.py").read_text()
    task_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_task.py").read_text()

    assert re.search(r"\bid:\s*Mapped\[TriggerId\].*?EntityIdType\(TriggerId\)", trigger_source, re.S)
    assert re.search(
        r"\btrigger_id:\s*Mapped\[Optional\[TriggerId\]\].*?EntityIdType\(TriggerId\)",
        task_source,
        re.S,
    )


def test_environment_models_keep_environment_identity_typed():
    environment_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_environment.py").read_text()
    audit_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_storage_mount.py").read_text()

    assert re.search(
        r"\bid:\s*Mapped\[EnvironmentId\].*?EntityIdType\(EnvironmentId\)",
        environment_source,
        re.S,
    )
    assert re.search(
        r"\benvironment_id:\s*Mapped\[Optional\[EnvironmentId\]\].*?EntityIdType\(EnvironmentId\)",
        audit_source,
        re.S,
    )


def test_secret_model_keeps_secret_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_secret.py").read_text()

    assert re.search(r"\bid:\s*Mapped\[SecretId\].*?EntityIdType\(SecretId\)", source, re.S)


def test_vault_models_keep_vault_and_credential_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_vault.py").read_text()

    assert re.search(r"class JoySafeterVault.*?\bid:\s*Mapped\[VaultId\].*?EntityIdType\(VaultId\)", source, re.S)
    assert re.search(
        r"class JoySafeterVaultCredential.*?\bid:\s*Mapped\[CredentialId\].*?EntityIdType\(CredentialId\)",
        source,
        re.S,
    )
    assert re.search(r"\bvault_id:\s*Mapped\[VaultId\].*?EntityIdType\(VaultId\)", source, re.S)


def test_sandbox_models_keep_sandbox_identity_typed():
    sandbox_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_sandbox.py").read_text()
    task_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_task.py").read_text()
    session_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session.py").read_text()
    policy_source = (
        BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_sandbox_network_policy.py"
    ).read_text()

    assert re.search(r"\bid:\s*Mapped\[SandboxId\].*?EntityIdType\(SandboxId\)", sandbox_source, re.S)
    assert re.search(
        r"\bsandbox_id:\s*Mapped\[Optional\[SandboxId\]\].*?EntityIdType\(SandboxId\)",
        task_source,
        re.S,
    )
    assert re.search(
        r"\blast_sandbox_id:\s*Mapped\[Optional\[SandboxId\]\].*?EntityIdType\(SandboxId\)",
        session_source,
        re.S,
    )
    assert re.search(r"\bsandbox_id:\s*Mapped\[SandboxId\].*?EntityIdType\(SandboxId\)", policy_source, re.S)


def test_memory_models_keep_memory_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_memory.py").read_text()

    assert re.search(r"class JoySafeterMemoryStore.*?\bid:\s*Mapped\[MemoryStoreId\]", source, re.S)
    assert re.search(r"class JoySafeterMemory.*?\bid:\s*Mapped\[MemoryId\]", source, re.S)
    assert re.search(r"\bstore_id:\s*Mapped\[MemoryStoreId\]", source)
    assert re.search(r"\bcurrent_version_id:\s*Mapped\[Optional\[MemoryVersionId\]\]", source)
    assert re.search(r"class JoySafeterMemoryVersion.*?\bid:\s*Mapped\[MemoryVersionId\]", source, re.S)


def test_skill_models_keep_skill_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_skill.py").read_text()

    expected = (
        ("JoySafeterSkill", "SkillId"),
        ("JoySafeterSkillFile", "SkillFileId"),
        ("JoySafeterSkillSecurityScan", "SkillSecurityScanId"),
        ("JoySafeterSkillVersion", "SkillVersionId"),
        ("JoySafeterSkillVersionFile", "SkillVersionFileId"),
        ("JoySafeterSkillUsageLog", "SkillUsageId"),
    )
    for model, id_type in expected:
        assert re.search(rf"class {model}.*?\bid:\s*Mapped\[{id_type}\]", source, re.S)


def test_file_and_session_resource_models_keep_identity_typed():
    file_source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_file.py").read_text()
    session_file_source = (
        BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session_file.py"
    ).read_text()
    session_repo_source = (
        BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session_repo.py"
    ).read_text()

    assert re.search(r"\bid:\s*Mapped\[FileId\].*?EntityIdType\(FileId\)", file_source, re.S)
    assert re.search(
        r"\bid:\s*Mapped\[SessionResourceId\].*?EntityIdType\(SessionResourceId\)",
        session_file_source,
        re.S,
    )
    assert re.search(
        r"\bfile_id:\s*Mapped\[FileId\].*?EntityIdType\(FileId\)",
        session_file_source,
        re.S,
    )
    assert re.search(
        r"\bid:\s*Mapped\[SessionResourceId\].*?EntityIdType\(SessionResourceId\)",
        session_repo_source,
        re.S,
    )


def test_storage_models_keep_resource_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_storage_mount.py").read_text()

    expected = (
        ("JoySafeterStorageVolume", "StorageVolumeId"),
        ("JoySafeterStorageProjectGrant", "StorageGrantId"),
        ("JoySafeterStorageOrganizationGrant", "StorageGrantId"),
        ("JoySafeterSessionStorageMount", "SessionResourceId"),
        ("JoySafeterStorageMountAudit", "StorageMountAuditId"),
    )
    for model, id_type in expected:
        assert re.search(
            rf"class {model}.*?\bid:\s*Mapped\[{id_type}\].*?EntityIdType\({id_type}\)",
            source,
            re.S,
        )
    assert source.count("volume_id: Mapped[StorageVolumeId]") == 3
    assert "volume_id: Mapped[Optional[StorageVolumeId]]" in source


def test_storage_response_schemas_keep_resource_identity_typed():
    storage_source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/joysafeter_storage_mount.py").read_text()
    session_source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/joysafeter_session.py").read_text()

    assert re.search(r"class StorageVolumeResponse.*?\bid:\s*StorageVolumeId", storage_source, re.S)
    assert storage_source.count("id: StorageGrantId") == 2
    assert storage_source.count("volume_id: StorageVolumeId") == 2
    assert re.search(
        r"class StorageMountAuditResponse.*?\bid:\s*StorageMountAuditId.*?"
        r"volume_id:\s*Optional\[StorageVolumeId\]",
        storage_source,
        re.S,
    )
    assert re.search(
        r"class SessionStorageMountResponse.*?\bid:\s*SessionResourceId.*?"
        r"volume_id:\s*StorageVolumeId",
        session_source,
        re.S,
    )


def test_session_event_model_keeps_event_identity_typed():
    source = (BACKEND_ROOT / "app/joysafeter_domain/models/joysafeter_session.py").read_text()
    assert re.search(
        r"class JoySafeterSessionEvent.*?\bid:\s*Mapped\[EventId\].*?EntityIdType\(EventId\)",
        source,
        re.S,
    )


def test_session_vault_ids_are_typed_before_jsonb_storage():
    schema_source = (BACKEND_ROOT / "app/joysafeter_domain/schemas/joysafeter_session.py").read_text()
    service_source = (BACKEND_ROOT / "app/joysafeter_domain/services/joysafeter_session_service.py").read_text()

    assert schema_source.count("vault_ids: list[VaultId]") == 2
    assert "vault_ids=[str(vault_id) for vault_id in vault_ids or []]" in service_source


def test_rust_orchestrator_has_no_bare_core_entity_uuid_annotations():
    rust_root = BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src"
    forbidden = re.compile(
        r"\b(?:(?:[A-Za-z0-9]+_)?(?:agent|session|task|environment|vault|credential|sandbox|memory_store|memory|memory_version|skill|file|session_resource|event)_id|store_id|resource_id)\s*:\s*(?:Option<)?Uuid"
    )
    matches = []
    for path in rust_root.rglob("*.rs"):
        if forbidden.search(path.read_text()):
            matches.append(str(path.relative_to(BACKEND_ROOT)))

    assert matches == []


def test_rust_entity_ids_cannot_implicitly_deref_to_uuid():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()

    assert "impl std::ops::Deref" not in rust_ids


def test_rust_environment_and_vault_identity_boundaries_are_typed():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_scheduler = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/scheduler.rs"
    ).read_text()
    rust_harness = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs"
    ).read_text()
    rust_resolver = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/sandbox_resolver.rs"
    ).read_text()

    assert 'entity_id!(EnvironmentId, "env_");' in rust_ids
    assert 'entity_id!(VaultId, "vault_");' in rust_ids
    assert 'entity_id!(CredentialId, "cred_");' in rust_ids
    assert "id: EnvironmentId" in rust_scheduler
    assert "EnvironmentId::from_public(normalized)" in rust_scheduler
    assert 'strip_prefix("env_").unwrap_or(normalized)' not in rust_scheduler
    assert "let ids: Vec<VaultId>" in rust_harness
    assert "id: CredentialId" in rust_harness
    assert "let ids: Vec<VaultId>" in rust_resolver


def test_rust_orchestrator_models_use_core_entity_ids():
    source = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/db/models.rs").read_text()

    def struct_body(name: str) -> str:
        match = re.search(rf"pub struct {name}\s*\{{(?P<body>.*?)\n\}}", source, re.S)
        assert match is not None, name
        return match.group("body")

    agent_model = struct_body("JoySafeterAgent")
    task_model = struct_body("JoySafeterTask")
    session_model = struct_body("JoySafeterSession")
    sandbox_model = struct_body("JoySafeterSandbox")

    assert re.search(r"\bpub id:\s*AgentId\b", agent_model)
    assert re.search(r"\bpub id:\s*TaskId\b", task_model)
    assert re.search(r"\bpub session_id:\s*Option<SessionId>", task_model)
    assert re.search(r"\bpub sandbox_id:\s*Option<SandboxId>", task_model)
    assert re.search(r"\bpub id:\s*SessionId\b", session_model)
    assert re.search(r"\bpub id:\s*SandboxId\b", sandbox_model)
    assert re.search(r"\bpub chat_session_id:\s*Option<SessionId>", sandbox_model)


def test_sandbox_physical_boundaries_explicitly_unwrap_typed_ids():
    python_runtime = (
        BACKEND_ROOT / "app/joysafeter_shared/orchestrator_bridge/runtime_commands.py"
    ).read_text()
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_redis = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/redis_coordinator.rs"
    ).read_text()
    rust_commands = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs"
    ).read_text()
    rust_k8s = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/sandbox/k8s.rs").read_text()

    assert 'entity_id!(SandboxId, "sbx_");' in rust_ids
    assert "sandbox_id_str = str(as_uuid(sandbox_id))" in python_runtime
    assert 'format!("joysafeter:sandbox_owner:{}", sandbox_id.as_uuid())' in rust_redis
    assert "sandbox_id.as_uuid().to_string()" in rust_redis
    assert "SandboxId::from_uuid(id)" in rust_commands
    assert '"sandbox_id": sandbox_id.as_uuid().to_string()' in rust_commands
    assert 'format!("joysafeter-{}", sandbox_id.as_uuid())' in rust_k8s
    assert "let sandbox_uuid = config.sandbox_id.as_uuid();" in rust_k8s


def test_memory_physical_boundaries_explicitly_unwrap_typed_ids():
    python_memory_api = (
        BACKEND_ROOT / "app/joysafeter_api/api/v1/memory_stores.py"
    ).read_text()
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_harness = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs"
    ).read_text()
    rust_commands = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/command_listener.rs"
    ).read_text()

    assert 'entity_id!(MemoryStoreId, "memstore_");' in rust_ids
    assert 'entity_id!(MemoryId, "mem_");' in rust_ids
    assert 'entity_id!(MemoryVersionId, "memver_");' in rust_ids
    assert '"store_id": str(as_uuid(store_id))' in python_memory_api
    assert "store_id: store.store_id.as_uuid().to_string()" in rust_harness
    assert ".map(MemoryStoreId::from_uuid)" in rust_commands
    assert ".notify_store_peers(" in rust_commands


def test_skill_public_and_physical_boundaries_use_typed_ids():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_harness = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/kernel/harness_input_builder.rs"
    ).read_text()

    for declaration in (
        'entity_id!(SkillId, "skill_");',
        'entity_id!(SkillFileId, "sklfile_");',
        'entity_id!(SkillSecurityScanId, "sklscan_");',
        'entity_id!(SkillVersionId, "sklver_");',
        'entity_id!(SkillVersionFileId, "sklvfile_");',
        'entity_id!(SkillUsageId, "skluse_");',
    ):
        assert declaration in rust_ids
    assert "SkillId::from_public(skill_id)" in rust_harness
    assert ".bind(SkillUsageId::from_uuid(Uuid::now_v7()))" in rust_harness


def test_file_public_and_physical_boundaries_use_typed_ids():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_query = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/db/queries/file.rs"
    ).read_text()
    rust_artifacts = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/sandbox/artifacts.rs"
    ).read_text()
    python_file_service = (
        BACKEND_ROOT / "app/joysafeter_domain/services/joysafeter_file_service.py"
    ).read_text()

    assert 'entity_id!(FileId, "file_");' in rust_ids
    assert 'entity_id!(SessionResourceId, "sesrsc_");' in rust_ids
    assert "id: FileId" in rust_query
    assert "Option<FileId>" in rust_artifacts
    assert "let raw_file_id = file_id.as_uuid();" in rust_artifacts
    assert "as_uuid(file_id)" in python_file_service


def test_event_public_and_physical_boundaries_use_typed_ids():
    rust_ids = (BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/ids.rs").read_text()
    rust_envelope = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/events/envelope.rs"
    ).read_text()
    rust_realtime = (
        BACKEND_ROOT / "app/joysafeter_orchestrator_rs/src/events/realtime.rs"
    ).read_text()
    python_session = (
        BACKEND_ROOT / "app/joysafeter_domain/services/joysafeter_session_service.py"
    ).read_text()

    assert 'entity_id!(EventId, "evt_");' in rust_ids
    assert "pub event_id: Option<EventId>" in rust_envelope
    assert "id.to_public()" in rust_realtime
    assert 'event["id"] = str(event_id)' in python_session
