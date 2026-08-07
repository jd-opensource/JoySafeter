import uuid

import pytest
from pydantic import BaseModel, ValidationError

from app.joysafeter_shared import ids as entity_ids
from app.joysafeter_shared.ids import (
    AgentId,
    EntityIdType,
    EnvironmentId,
    EventId,
    FileId,
    SessionId,
    SessionResourceId,
    SkillFileId,
    SkillId,
    SkillSecurityScanId,
    SkillUsageId,
    SkillVersionFileId,
    SkillVersionId,
    TaskId,
    as_uuid,
)

pytestmark = pytest.mark.no_db


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


def test_physical_uuid_adapter_rejects_string_compatibility():
    agent_id = AgentId.new()

    assert as_uuid(agent_id) == agent_id.uuid
    with pytest.raises(TypeError, match="cannot unwrap str as UUID"):
        as_uuid(str(agent_id))  # type: ignore[arg-type]


def test_entity_id_type_binds_only_native_uuid_or_matching_entity_id():
    value = uuid.uuid4()
    adapter = EntityIdType(AgentId)

    assert adapter.process_bind_param(value, None) == value
    assert adapter.process_bind_param(AgentId.from_uuid(value), None) == value
    with pytest.raises(TypeError):
        adapter.process_bind_param(str(value), None)


def test_cross_type_inequality():
    u = uuid.uuid4()
    assert AgentId(u) != SessionId(u)


def test_cross_entity_construction_raises():
    with pytest.raises(TypeError):
        AgentId(SessionId(uuid.uuid4()))


def test_wrong_prefix_rejected():
    with pytest.raises(ValueError):
        AgentId.from_public(f"sesn_{uuid.uuid4()}")


def test_new_is_unique_and_typed():
    a, b = AgentId.new(), AgentId.new()
    assert isinstance(a, AgentId) and a != b


@pytest.mark.parametrize(
    ("id_type", "prefix"),
    [
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


def test_public_factory_requires_canonical_prefix():
    with pytest.raises(ValueError, match="expected agent_ prefix"):
        AgentId.from_public(str(uuid.uuid4()))


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
        id=uuid.uuid4(),
        environment_id=environment_id,
        action="environment.mount",
        result="success",
        created_at=now,
    )

    assert environment.model_dump(mode="json")["id"] == str(environment_id)
    assert audit.model_dump(mode="json")["environment_id"] == str(environment_id)
