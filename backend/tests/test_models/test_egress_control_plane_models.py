import pytest

from app.joysafeter_domain.models.joysafeter_egress_control import (
    JoySafeterEgressApplyStatus,
    JoySafeterEgressGroupGeneration,
    JoySafeterEgressNodeApplyStatus,
    JoySafeterEgressNodeConnection,
    JoySafeterEgressOutboxEvent,
)

pytestmark = pytest.mark.no_db


def test_egress_control_plane_tables_are_registered() -> None:
    assert JoySafeterEgressGroupGeneration.__tablename__ == "joysafeter_egress_group_generations"
    assert JoySafeterEgressOutboxEvent.__tablename__ == "joysafeter_egress_outbox_events"
    assert JoySafeterEgressApplyStatus.__tablename__ == "joysafeter_egress_apply_status"
    assert JoySafeterEgressNodeConnection.__tablename__ == "joysafeter_egress_node_connections"
    assert JoySafeterEgressNodeApplyStatus.__tablename__ == "joysafeter_egress_node_apply_status"


def test_egress_control_plane_schema_has_no_secret_value_columns() -> None:
    forbidden_fragments = ("secret", "credential_value", "token_value", "api_key", "password")
    models = (
        JoySafeterEgressGroupGeneration,
        JoySafeterEgressOutboxEvent,
        JoySafeterEgressApplyStatus,
        JoySafeterEgressNodeConnection,
        JoySafeterEgressNodeApplyStatus,
    )
    for model in models:
        column_names = tuple(column.name.lower() for column in model.__table__.columns)
        assert not any(fragment in name for name in column_names for fragment in forbidden_fragments)


def test_egress_event_log_is_not_a_claim_queue() -> None:
    column_names = {column.name for column in JoySafeterEgressOutboxEvent.__table__.columns}
    assert column_names == {"id", "group_key", "generation", "event_type", "created_at", "updated_at"}

    queue_only_columns = {
        "attempts",
        "available_at",
        "claimed_by",
        "claimed_until",
        "last_error",
        "published_at",
    }
    assert column_names.isdisjoint(queue_only_columns)

    index_names = {index.name for index in JoySafeterEgressOutboxEvent.__table__.indexes}
    assert "idx_egress_outbox_generation" in index_names
    assert "idx_egress_outbox_pending" not in index_names
