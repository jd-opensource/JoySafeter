import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_egress_generation_outbox_and_apply_status_round_trip(db_session: AsyncSession) -> None:
    group_key = "v1:" + ("A" * 43)
    generation = 1
    selector = {
        "deployment_id": "test",
        "environment": "test",
        "region": "local",
        "provider": "k8s",
        "shard_id": "0",
        "envoy_version": "1.39.0",
        "config_schema_version": "1",
    }
    await db_session.execute(
        text(
            """
            INSERT INTO joysafeter_egress_node_connections (
                id, group_key, node_id, controller_instance, envoy_version,
                last_seen_at, lease_expires_at
            ) VALUES (
                :id, :group_key, 'envoy-1', 'controller-1', '1.39.0',
                :last_seen_at, :lease_expires_at
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "group_key": group_key,
            "last_seen_at": datetime.now(UTC),
            "lease_expires_at": datetime.now(UTC) + timedelta(seconds=30),
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO joysafeter_egress_group_generations (
                id, group_key, generation, node_selector, policy_schema_version,
                desired_policies, content_sha256, state
            ) VALUES (
                :id, :group_key, :generation, CAST(:selector AS jsonb), 1,
                CAST(:policies AS jsonb), :content_sha256, 'desired'
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "group_key": group_key,
            "generation": generation,
            "selector": json.dumps(selector),
            "policies": "[]",
            "content_sha256": "0" * 64,
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO joysafeter_egress_outbox_events (
                id, group_key, generation, event_type
            ) VALUES (
                :id, :group_key, :generation, 'egress.group_generation.desired'
            )
            """
        ),
        {"id": uuid.uuid4(), "group_key": group_key, "generation": generation},
    )
    await db_session.execute(
        text(
            """
            INSERT INTO joysafeter_egress_apply_status (
                id, group_key, generation, xds_version, required_type_urls, state,
                connected_nodes, required_acks, acked_acks
            ) VALUES (
                :id, :group_key, :generation, 'g1-test', CAST(:required_types AS jsonb),
                'published', 1, 2, 1
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "group_key": group_key,
            "generation": generation,
            "required_types": json.dumps(
                [
                    "type.googleapis.com/envoy.config.cluster.v3.Cluster",
                    "type.googleapis.com/envoy.config.listener.v3.Listener",
                ]
            ),
        },
    )
    await db_session.execute(
        text(
            """
            INSERT INTO joysafeter_egress_node_apply_status (
                id, group_key, generation, node_id, type_url, xds_version,
                status, nonce_sha256, controller_instance
            ) VALUES (
                :id, :group_key, :generation, 'envoy-1',
                'type.googleapis.com/envoy.config.listener.v3.Listener',
                'g1-test', 'ack', :nonce_sha256, 'controller-1'
            )
            """
        ),
        {
            "id": uuid.uuid4(),
            "group_key": group_key,
            "generation": generation,
            "nonce_sha256": "1" * 64,
        },
    )
    await db_session.commit()

    counts = await db_session.execute(
        text(
            """
            SELECT
                (SELECT count(*) FROM joysafeter_egress_group_generations),
                (SELECT count(*) FROM joysafeter_egress_outbox_events),
                (SELECT count(*) FROM joysafeter_egress_node_connections),
                (SELECT count(*) FROM joysafeter_egress_apply_status),
                (SELECT count(*) FROM joysafeter_egress_node_apply_status)
            """
        )
    )
    assert counts.one() == (1, 1, 1, 1, 1)

    outbox_columns = await db_session.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'joysafeter_egress_outbox_events'
            ORDER BY ordinal_position
            """
        )
    )
    assert [row[0] for row in outbox_columns] == [
        "id",
        "group_key",
        "generation",
        "event_type",
        "created_at",
        "updated_at",
    ]

    outbox_pending_index = await db_session.execute(
        text(
            """
            SELECT count(*)
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'joysafeter_egress_outbox_events'
              AND indexname = 'idx_egress_outbox_pending'
            """
        )
    )
    assert outbox_pending_index.scalar_one() == 0

    outbox_generation_index = await db_session.execute(
        text(
            """
            SELECT count(*)
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = 'joysafeter_egress_outbox_events'
              AND indexname = 'idx_egress_outbox_generation'
            """
        )
    )
    assert outbox_generation_index.scalar_one() == 1

    trigger = await db_session.execute(
        text(
            """
            SELECT count(*)
            FROM pg_trigger
            WHERE tgname = 'trg_joysafeter_egress_generation_notify'
              AND NOT tgisinternal
            """
        )
    )
    assert trigger.scalar_one() == 1

    immutable_trigger = await db_session.execute(
        text(
            """
            SELECT count(*)
            FROM pg_trigger
            WHERE tgname = 'trg_joysafeter_egress_generation_immutable'
              AND NOT tgisinternal
            """
        )
    )
    assert immutable_trigger.scalar_one() == 1

    savepoint = await db_session.begin_nested()
    with pytest.raises(DBAPIError):
        await db_session.execute(
            text(
                """
                UPDATE joysafeter_egress_group_generations
                SET desired_policies = '[{"sandbox_id":"tampered"}]'::jsonb
                WHERE group_key = :group_key AND generation = :generation
                """
            ),
            {"group_key": group_key, "generation": generation},
        )
    await savepoint.rollback()

    await db_session.execute(
        text(
            """
            UPDATE joysafeter_egress_group_generations
            SET state = 'superseded', superseded_at = now(), updated_at = now()
            WHERE group_key = :group_key AND generation = :generation
            """
        ),
        {"group_key": group_key, "generation": generation},
    )
