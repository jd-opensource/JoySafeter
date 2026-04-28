# backend/tests/test_core/test_observation/test_model.py
from __future__ import annotations
import uuid
from datetime import datetime, timezone

from app.core.observation.model import Observation, Trace
from app.core.observation.types import ObservationLevel, ObservationType


def test_trace_meta_column_named_metadata() -> None:
    col = Trace.__table__.columns["metadata"]
    assert col is not None
    assert "meta" in {a.key for a in Trace.__mapper__.attrs}


def test_observation_meta_column_named_metadata() -> None:
    col = Observation.__table__.columns["metadata"]
    assert col is not None
    assert "meta" in {a.key for a in Observation.__mapper__.attrs}


def test_trace_required_fields() -> None:
    cols = Trace.__table__.columns
    for required in ("id", "name", "workspace_id", "start_time", "status",
                     "execution_id", "agent_version_id", "user_id"):
        assert cols[required].nullable is False, f"{required} must be NOT NULL"


def test_observation_required_fields() -> None:
    cols = Observation.__table__.columns
    for required in ("id", "trace_id", "type", "name", "level",
                     "start_time", "execution_id", "workspace_id"):
        assert cols[required].nullable is False, f"{required} must be NOT NULL"


def test_observation_parent_fk_self_reference() -> None:
    col = Observation.__table__.columns["parent_observation_id"]
    assert col.nullable is True


def test_trace_default_status_running() -> None:
    cols = Trace.__table__.columns
    assert cols["status"].server_default is not None


def test_observation_default_level_default() -> None:
    cols = Observation.__table__.columns
    assert cols["level"].server_default is not None


def test_trace_can_instantiate_with_minimum_fields() -> None:
    t = Trace(
        id=uuid.uuid4(),
        name="test agent",
        workspace_id=uuid.uuid4(),
        start_time=datetime.now(timezone.utc),
        status="running",
        execution_id=uuid.uuid4(),
        agent_version_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
    )
    assert t.name == "test agent"


def test_observation_can_instantiate_with_minimum_fields() -> None:
    o = Observation(
        id=uuid.uuid4(),
        trace_id=uuid.uuid4(),
        type=ObservationType.GENERATION,
        name="gpt-4o",
        level=ObservationLevel.DEFAULT,
        start_time=datetime.now(timezone.utc),
        execution_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
    )
    assert o.type == "GENERATION"
