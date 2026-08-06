# backend/tests/test_entity_id_type.py
import uuid
import pytest
from app.joysafeter_shared.ids import AgentId, EntityIdType

pytestmark = pytest.mark.no_db


def test_bind_unwraps_typed_id():
    t = EntityIdType(AgentId)
    u = uuid.uuid4()
    assert t.process_bind_param(AgentId(u), None) == u


def test_bind_accepts_bare_uuid_and_str():
    t = EntityIdType(AgentId)
    u = uuid.uuid4()
    assert t.process_bind_param(u, None) == u
    assert t.process_bind_param(f"agent_{u}", None) == u


def test_bind_none_passthrough():
    assert EntityIdType(AgentId).process_bind_param(None, None) is None


def test_result_wraps_into_typed_id():
    t = EntityIdType(AgentId)
    u = uuid.uuid4()
    got = t.process_result_value(u, None)
    assert got == AgentId(u) and isinstance(got, AgentId)


def test_result_none_passthrough():
    assert EntityIdType(AgentId).process_result_value(None, None) is None
