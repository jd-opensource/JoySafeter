import uuid
import pytest
from pydantic import BaseModel
from app.joysafeter_shared.ids import AgentId, SessionId, TaskId

pytestmark = pytest.mark.no_db


def test_str_roundtrip_adds_prefix():
    u = uuid.uuid4()
    assert str(AgentId(u)) == f"agent_{u}"


def test_accepts_prefixed_string():
    u = uuid.uuid4()
    assert AgentId(f"agent_{u}").uuid == u


def test_accepts_bare_uuid_string():
    u = uuid.uuid4()
    assert AgentId(str(u)).uuid == u


def test_cross_type_inequality():
    u = uuid.uuid4()
    assert AgentId(u) != SessionId(u)


def test_cross_entity_construction_raises():
    with pytest.raises(TypeError):
        AgentId(SessionId(uuid.uuid4()))


def test_wrong_prefix_rejected():
    with pytest.raises(ValueError):
        AgentId(f"sesn_{uuid.uuid4()}")


def test_new_is_unique_and_typed():
    a, b = AgentId.new(), AgentId.new()
    assert isinstance(a, AgentId) and a != b


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


def test_task_response_serializes_agent_id_prefix():
    import datetime

    from app.joysafeter_domain.schemas.joysafeter_task import JoySafeterTaskResponse
    from app.joysafeter_shared.ids import AgentId

    # Task's own PK migration is a later task, so ``id`` is still a bare uuid here;
    # ``agent_id`` is the Agent-owned field this task migrates to ``AgentId``.
    aid, tid = uuid.uuid4(), uuid.uuid4()
    resp = JoySafeterTaskResponse.model_validate(
        {
            "id": tid,
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
