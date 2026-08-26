import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jose import jwt
from pydantic import BaseModel, ValidationError

from app.joysafeter_shared import ids as entity_ids
from app.joysafeter_shared.config.settings import settings
from app.joysafeter_shared.ids import (
    AgentId,
    AgentVersionId,
    ApiKeyId,
    EnvironmentId,
    EventId,
    FileId,
    OrganizationId,
    ProjectId,
    SessionId,
    SessionResourceId,
    SkillFileId,
    SkillId,
    SkillSecurityScanId,
    SkillUsageId,
    SkillVersionFileId,
    SkillVersionId,
    StorageMountAuditId,
    TaskId,
    UserId,
    as_uuid,
)
from app.joysafeter_shared.security import create_access_token, create_csrf_token, decode_token
from app.joysafeter_shared.sqlalchemy_ids import EntityIdType

pytestmark = pytest.mark.no_db
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_entity_id_value_module_does_not_load_persistence_or_validation_frameworks():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import app.joysafeter_shared.ids; "
                "assert not any(name == 'sqlalchemy' or name.startswith('sqlalchemy.') for name in sys.modules); "
                "assert not any(name == 'pydantic' or name.startswith('pydantic.') for name in sys.modules)"
            ),
        ],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_str_roundtrip_adds_prefix():
    u = uuid.uuid4()
    assert str(AgentId(u)) == f"agent_{u}"


def test_direct_constructor_rejects_all_strings():
    value = uuid.uuid4()

    with pytest.raises(TypeError, match="cannot build AgentId from str"):
        AgentId(str(value))
    with pytest.raises(TypeError, match="cannot build AgentId from str"):
        AgentId(f"agent_{value}")


def test_named_factories_separate_public_and_physical_values():
    value = uuid.uuid4()

    assert AgentId.from_uuid(value).uuid == value
    assert AgentId.from_public(f"agent_{value}").uuid == value
    with pytest.raises(ValueError, match="expected agent_ prefix"):
        AgentId.from_public(str(value))


def test_physical_uuid_adapter_accepts_only_typed_entity_ids():
    agent_id = AgentId.new()

    assert as_uuid(agent_id) == agent_id.uuid
    with pytest.raises(TypeError, match="cannot unwrap str as UUID"):
        as_uuid(str(agent_id))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="cannot unwrap UUID as UUID"):
        as_uuid(agent_id.uuid)  # type: ignore[arg-type]


def test_entity_id_type_enforces_typed_bind_and_hydration():
    value = uuid.uuid4()
    adapter = EntityIdType(AgentId)

    assert adapter.process_bind_param(AgentId.from_uuid(value), None) == value
    assert adapter.process_bind_param(None, None) is None
    with pytest.raises(TypeError):
        adapter.process_bind_param(value, None)
    with pytest.raises(TypeError):
        adapter.process_bind_param(str(value), None)

    hydrated = adapter.process_result_value(value, None)
    assert hydrated == AgentId.from_uuid(value)
    assert type(hydrated) is AgentId
    assert adapter.process_result_value(None, None) is None


def test_cross_type_inequality():
    u = uuid.uuid4()
    assert AgentId(u) != SessionId(u)


def test_cross_entity_construction_raises():
    with pytest.raises(TypeError):
        AgentId(SessionId(uuid.uuid4()))


def test_access_token_roundtrip_preserves_typed_tenant_claims():
    user_id = UserId.new()
    organization_id = OrganizationId.new()
    project_id = ProjectId.new()

    payload = decode_token(
        create_access_token(
            subject=user_id,
            org_id=organization_id,
            project_id=project_id,
            role="admin",
        )
    )

    assert payload is not None
    assert payload.sub == user_id
    assert payload.org_id == organization_id
    assert payload.project_id == project_id


@pytest.mark.parametrize(
    ("claim", "value"),
    [
        ("sub", str(uuid.uuid4())),
        ("sub", str(ProjectId.new())),
        ("org_id", str(uuid.uuid4())),
        ("org_id", str(ProjectId.new())),
        ("project_id", str(uuid.uuid4())),
        ("project_id", str(OrganizationId.new())),
    ],
)
def test_decode_token_rejects_bare_or_cross_entity_tenant_claims(claim: str, value: str):
    claims = {
        "sub": str(UserId.new()),
        "org_id": str(OrganizationId.new()),
        "project_id": str(ProjectId.new()),
        "role": "admin",
        "type": "access",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims[claim] = value
    token = jwt.encode(claims, settings.secret_key, algorithm=settings.algorithm)

    assert decode_token(token) is None


def test_token_creation_rejects_string_identity_bridges():
    user_id = UserId.new()

    with pytest.raises(TypeError, match="subject must be UserId"):
        create_access_token(subject=str(user_id))
    with pytest.raises(TypeError, match="org_id must be OrganizationId"):
        create_access_token(subject=user_id, org_id=str(OrganizationId.new()))
    with pytest.raises(TypeError, match="project_id must be ProjectId"):
        create_access_token(subject=user_id, project_id=str(ProjectId.new()))
    with pytest.raises(TypeError, match="user_id must be UserId"):
        create_csrf_token(str(user_id))


def test_wrong_prefix_rejected():
    with pytest.raises(ValueError):
        AgentId.from_public(f"sesn_{uuid.uuid4()}")


def test_new_is_unique_and_typed():
    a, b = AgentId.new(), AgentId.new()
    assert isinstance(a, AgentId) and a != b


@pytest.mark.parametrize(
    ("id_type", "prefix"),
    [
        (AgentVersionId, "agentver_"),
        (ApiKeyId, "apikey_"),
        (SkillId, "skill_"),
        (SkillFileId, "sklfile_"),
        (SkillSecurityScanId, "sklscan_"),
        (SkillVersionId, "sklver_"),
        (SkillVersionFileId, "sklvfile_"),
        (SkillUsageId, "skluse_"),
        (FileId, "file_"),
        (SessionResourceId, "sesrsc_"),
        (EventId, "evt_"),
    ],
)
def test_entity_id_prefix_contract(id_type, prefix: str):
    value = uuid.uuid4()

    assert str(id_type.from_uuid(value)) == f"{prefix}{value}"
    assert id_type.from_public(f"{prefix}{value}").uuid == value


def test_storage_entity_id_prefix_inventory_and_public_contract():
    expected = {
        "StorageVolumeId": "vol_",
        "StorageGrantId": "stgrant_",
        "StorageMountAuditId": "staudit_",
    }

    for name, prefix in expected.items():
        id_type = getattr(entity_ids, name, None)
        assert id_type is not None, name
        value = uuid.uuid4()
        typed_id = id_type.from_uuid(value)

        assert typed_id.uuid == value
        assert str(typed_id) == f"{prefix}{value}"
        assert id_type.from_public(str(typed_id)) == typed_id
        with pytest.raises(ValueError):
            id_type.from_public(str(value))
        with pytest.raises(ValueError):
            id_type.from_public(f"agent_{value}")

        class Response(BaseModel):
            id: id_type

        assert Response(id=str(typed_id)).model_dump(mode="json") == {"id": str(typed_id)}
        with pytest.raises(ValidationError):
            Response(id=str(value))


def test_tenant_auth_and_internal_record_id_prefix_inventory():
    expected = {
        "UserId": "user_",
        "OrganizationId": "org_",
        "OrganizationMemberId": "orgmem_",
        "ProjectId": "proj_",
        "ProjectMemberId": "projmem_",
        "OAuthAccountId": "oauthacct_",
        "AuthSessionId": "authsess_",
        "CredentialAccessAuditId": "credaudit_",
        "SecurityAuditId": "secaudit_",
        "SandboxNetworkPolicyId": "sbxnetpol_",
    }

    for name, prefix in expected.items():
        id_type = getattr(entity_ids, name, None)
        assert id_type is not None, f"missing canonical ID type: {name}"
        value = uuid.uuid4()
        typed_id = id_type.from_uuid(value)

        assert typed_id.uuid == value
        assert str(typed_id) == f"{prefix}{value}"
        assert id_type.from_public(str(typed_id)) == typed_id


def test_entity_columns_use_their_canonical_sqlalchemy_types():
    from app.joysafeter_domain import models as _models  # noqa: F401
    from app.joysafeter_shared.database import Base

    expected = {
        "joysafeter_agent_versions": {"id": "AgentVersionId", "agent_id": "AgentId"},
        "joysafeter_agents": {
            "id": "AgentId",
            "project_id": "ProjectId",
            "environment_id": "EnvironmentId",
            "model_credential_id": "CredentialId",
        },
        "joysafeter_api_keys": {
            "id": "ApiKeyId",
            "project_id": "ProjectId",
            "org_id": "OrganizationId",
            "created_by": "UserId",
        },
        "joysafeter_users": {"id": "UserId"},
        "joysafeter_auth_sessions": {
            "id": "AuthSessionId",
            "user_id": "UserId",
            "active_organization_id": "OrganizationId",
        },
        "joysafeter_organizations": {"id": "OrganizationId"},
        "joysafeter_organization_members": {
            "id": "OrganizationMemberId",
            "user_id": "UserId",
            "organization_id": "OrganizationId",
        },
        "joysafeter_organization_projects": {
            "id": "ProjectId",
            "org_id": "OrganizationId",
            "created_by_user_id": "UserId",
        },
        "joysafeter_project_members": {
            "id": "ProjectMemberId",
            "project_id": "ProjectId",
            "user_id": "UserId",
        },
        "joysafeter_oauth_account": {"id": "OAuthAccountId", "user_id": "UserId"},
        "joysafeter_credentials": {
            "id": "CredentialId",
            "project_id": "ProjectId",
            "group_id": "CredentialGroupId",
        },
        "joysafeter_credential_groups": {"id": "CredentialGroupId", "project_id": "ProjectId"},
        "joysafeter_credential_access_audits": {
            "id": "CredentialAccessAuditId",
            "project_id": "ProjectId",
            "credential_id": "CredentialId",
            "user_id": "UserId",
            "org_id": "OrganizationId",
            "session_id": "SessionId",
            "task_id": "TaskId",
        },
        "joysafeter_environments": {"id": "EnvironmentId", "project_id": "ProjectId"},
        "joysafeter_files": {"id": "FileId", "project_id": "ProjectId", "session_id": "SessionId"},
        "joysafeter_memories": {
            "id": "MemoryId",
            "store_id": "MemoryStoreId",
            "current_version_id": "MemoryVersionId",
        },
        "joysafeter_memory_stores": {"id": "MemoryStoreId", "project_id": "ProjectId"},
        "joysafeter_memory_versions": {
            "id": "MemoryVersionId",
            "store_id": "MemoryStoreId",
            "memory_id": "MemoryId",
            "session_id": "SessionId",
            "api_key_id": "ApiKeyId",
        },
        "joysafeter_sandboxes": {
            "id": "SandboxId",
            "project_id": "ProjectId",
            "chat_session_id": "SessionId",
            "last_task_id": "TaskId",
        },
        "joysafeter_security_audit_logs": {"id": "SecurityAuditId", "user_id": "UserId"},
        "joysafeter_session_credential_groups": {
            "session_id": "SessionId",
            "credential_group_id": "CredentialGroupId",
        },
        "joysafeter_session_events": {"id": "EventId", "session_id": "SessionId"},
        "joysafeter_session_files": {
            "id": "SessionResourceId",
            "session_id": "SessionId",
            "file_id": "FileId",
        },
        "joysafeter_session_memory_stores": {
            "id": "SessionResourceId",
            "session_id": "SessionId",
            "store_id": "MemoryStoreId",
        },
        "joysafeter_session_repos": {"id": "SessionResourceId", "session_id": "SessionId"},
        "joysafeter_session_storage_mounts": {
            "id": "SessionResourceId",
            "session_id": "SessionId",
            "volume_id": "StorageVolumeId",
            "project_id": "ProjectId",
        },
        "joysafeter_sessions": {
            "id": "SessionId",
            "project_id": "ProjectId",
            "agent_id": "AgentId",
            "environment_id": "EnvironmentId",
            "last_sandbox_id": "SandboxId",
        },
        "joysafeter_skill_files": {"id": "SkillFileId", "skill_id": "SkillId"},
        "joysafeter_skills": {
            "id": "SkillId",
            "owner_id": "UserId",
            "created_by_id": "UserId",
            "project_id": "ProjectId",
            "security_scan_id": "SkillSecurityScanId",
            "org_version_id": "SkillVersionId",
            "public_version_id": "SkillVersionId",
        },
        "joysafeter_skill_security_scans": {
            "id": "SkillSecurityScanId",
            "skill_id": "SkillId",
            "project_id": "ProjectId",
            "owner_id": "UserId",
            "created_by_id": "UserId",
        },
        "joysafeter_skill_versions": {
            "id": "SkillVersionId",
            "skill_id": "SkillId",
            "published_by_id": "UserId",
            "security_scan_id": "SkillSecurityScanId",
            "approved_by_id": "UserId",
        },
        "joysafeter_skill_version_files": {"id": "SkillVersionFileId", "version_id": "SkillVersionId"},
        "joysafeter_skill_usage_log": {
            "id": "SkillUsageId",
            "skill_id": "SkillId",
            "skill_version_id": "SkillVersionId",
            "security_scan_id": "SkillSecurityScanId",
            "session_id": "SessionId",
            "agent_id": "AgentId",
            "project_id": "ProjectId",
            "user_id": "UserId",
        },
        "joysafeter_storage_volumes": {"id": "StorageVolumeId"},
        "joysafeter_storage_project_grants": {
            "id": "StorageGrantId",
            "volume_id": "StorageVolumeId",
            "project_id": "ProjectId",
        },
        "joysafeter_storage_organization_grants": {
            "id": "StorageGrantId",
            "volume_id": "StorageVolumeId",
            "org_id": "OrganizationId",
        },
        "joysafeter_storage_mount_audit": {
            "id": "StorageMountAuditId",
            "volume_id": "StorageVolumeId",
            "project_id": "ProjectId",
            "session_id": "SessionId",
            "environment_id": "EnvironmentId",
            "user_id": "UserId",
        },
        "joysafeter_task_identity_contexts": {
            "task_id": "TaskId",
            "project_id": "ProjectId",
            "user_id": "UserId",
        },
        "joysafeter_tasks": {
            "id": "TaskId",
            "project_id": "ProjectId",
            "user_id": "UserId",
            "org_id": "OrganizationId",
            "agent_id": "AgentId",
            "chat_session_id": "SessionId",
            "sandbox_id": "SandboxId",
            "trigger_id": "TriggerId",
        },
        "joysafeter_triggers": {
            "id": "TriggerId",
            "agent_id": "AgentId",
            "environment_id": "EnvironmentId",
            "pinned_session_id": "SessionId",
            "reusable_session_id": "SessionId",
            "webhook_auth_credential_id": "CredentialId",
            "project_id": "ProjectId",
            "user_id": "UserId",
            "org_id": "OrganizationId",
            "last_task_id": "TaskId",
            "last_session_id": "SessionId",
        },
        "joysafeter_sandbox_network_policies": {
            "id": "SandboxNetworkPolicyId",
            "sandbox_id": "SandboxId",
            "session_id": "SessionId",
            "task_id": "TaskId",
        },
    }

    mismatches = []
    for table_name, columns in expected.items():
        table = Base.metadata.tables[table_name]
        for column_name, id_type_name in columns.items():
            column_type = table.c[column_name].type
            if not isinstance(column_type, EntityIdType):
                mismatches.append(f"{table_name}.{column_name}: {column_type!r}")
            elif column_type.id_cls is not getattr(entity_ids, id_type_name):
                mismatches.append(f"{table_name}.{column_name}: {column_type.id_cls.__name__}, expected {id_type_name}")

    assert not mismatches, "\n".join(mismatches)


def test_public_factory_requires_canonical_prefix():
    with pytest.raises(ValueError, match="expected agent_ prefix"):
        AgentId.from_public(str(uuid.uuid4()))


@pytest.mark.parametrize(
    "non_canonical_uuid",
    [
        lambda value: str(value).upper(),
        lambda value: value.hex,
        lambda value: f"{{{value}}}",
    ],
)
def test_public_factory_rejects_non_canonical_uuid_spellings(non_canonical_uuid):
    value = uuid.uuid4()

    with pytest.raises(ValueError, match="canonical agent_ entity ID"):
        AgentId.from_public(f"agent_{non_canonical_uuid(value)}")


def test_rejects_arbitrary_stringifiable_objects():
    class LooksLikeUuid:
        def __str__(self) -> str:
            return str(uuid.uuid4())

    with pytest.raises(TypeError):
        AgentId(LooksLikeUuid())  # type: ignore[arg-type]


def test_hash_by_type_and_uuid():
    u = uuid.uuid4()
    assert hash(AgentId(u)) == hash(AgentId(u))
    assert hash(AgentId(u)) != hash(SessionId(u))


def test_pydantic_validate_and_serialize():
    class M(BaseModel):
        id: TaskId

    u = uuid.uuid4()
    m = M(id=f"task_{u}")
    assert m.id == TaskId(u)
    assert m.model_dump(mode="json")["id"] == f"task_{u}"


def test_pydantic_public_input_rejects_bare_uuid_string():
    class M(BaseModel):
        id: TaskId

    with pytest.raises(ValueError):
        M(id=str(uuid.uuid4()))


def test_pydantic_entity_id_rejects_native_uuid_objects():
    class M(BaseModel):
        id: TaskId

    with pytest.raises(ValidationError):
        M(id=uuid.uuid4())


def test_task_response_serializes_agent_id_prefix():
    import datetime

    from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse
    from app.joysafeter_shared.ids import AgentId

    aid, tid = uuid.uuid4(), uuid.uuid4()
    resp = JoySafeterTaskResponse.model_validate(
        {
            "id": TaskId(tid),
            "agent_id": AgentId(aid),
            "status": "completed",
            "prompt": "x",
            "timeout_sec": 1,
            "retry_count": 0,
            "max_retries": 0,
            "created_at": datetime.datetime.now(datetime.UTC),
        }
    )
    assert resp.model_dump(mode="json")["agent_id"] == f"agent_{aid}"


def test_create_session_agent_alias_rejects_bare_uuid_string():
    from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest

    with pytest.raises(ValidationError):
        CreateSessionRequest(agent=str(uuid.uuid4()))


def test_create_session_agent_alias_accepts_canonical_agent_id():
    from app.joysafeter_domain.schemas.joysafeter_session import CreateSessionRequest

    agent_id = AgentId.new()
    request = CreateSessionRequest(agent=str(agent_id))

    assert request.agent is None
    assert request.agent_id == agent_id


def test_environment_responses_serialize_canonical_environment_ids():
    import datetime

    from app.joysafeter_domain.schemas.joysafeter_environment import EnvironmentResponse
    from app.joysafeter_domain.schemas.joysafeter_storage_mount import StorageMountAuditResponse

    environment_id = EnvironmentId.new()
    now = datetime.datetime.now(datetime.UTC)

    environment = EnvironmentResponse(
        id=environment_id,
        name="runtime",
        created_at=now,
        updated_at=now,
    )
    audit = StorageMountAuditResponse(
        id=StorageMountAuditId.new(),
        environment_id=environment_id,
        action="environment.mount",
        result="success",
        created_at=now,
    )

    assert environment.model_dump(mode="json")["id"] == str(environment_id)
    assert audit.model_dump(mode="json")["environment_id"] == str(environment_id)
