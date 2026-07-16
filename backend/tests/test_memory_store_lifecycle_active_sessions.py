import json
import uuid
from types import SimpleNamespace

import pytest
from error_contract_helpers import handled_app_error_payload
from sqlalchemy import select

from app.joysafeter_api.api.v1.memory_stores import (
    _broadcast_memory_update,
    archive_memory_store,
    create_memory,
    delete_memory,
    delete_memory_store,
    get_memory_store,
    list_memories,
    redact_memory_version,
    update_memory,
)
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_memory import (
    JoySafeterMemory,
    JoySafeterMemoryStore,
    JoySafeterSessionMemoryStore,
)
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession
from app.joysafeter_domain.schemas.joysafeter_memory import CreateMemoryRequest, UpdateMemoryRequest
from app.joysafeter_shared.common.app_errors import AppError
from app.joysafeter_shared.common.joysafeter_auth import JoySafeterAuthContext, JoySafeterRole
from app.joysafeter_shared.utils.datetime import utc_now


def _auth_ctx() -> JoySafeterAuthContext:
    return JoySafeterAuthContext(
        user_id="test-user",
        org_id="test-org",
        project_id=None,  # type: ignore[arg-type]
        role=JoySafeterRole.DEVELOPER,
    )


class _FakeRedis:
    def __init__(self, owners: dict[uuid.UUID, str]):
        self.owners = owners
        self.published: list[tuple[str, str]] = []

    async def get(self, key: str):
        sandbox_id = uuid.UUID(key.rsplit(":", 1)[-1])
        return self.owners.get(sandbox_id)

    async def publish(self, channel: str, payload: str):
        self.published.append((channel, payload))


async def _mounted_store(db_session):
    store = JoySafeterMemoryStore(name=f"store-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"memory-agent-{uuid.uuid4()}")
    db_session.add_all([store, agent])
    await db_session.commit()
    await db_session.refresh(store)
    await db_session.refresh(agent)

    session = JoySafeterSession(agent_id=agent.id, status="idle")
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    mount = JoySafeterSessionMemoryStore(
        session_id=session.id,
        store_id=store.id,
        access="read_write",
        mount_name="main",
    )
    db_session.add(mount)
    await db_session.commit()
    return store.id


async def _mounted_store_with_active_sandboxes(db_session):
    store = JoySafeterMemoryStore(name=f"store-{uuid.uuid4()}", description="")
    agent = JoySafeterAgent(name=f"memory-agent-{uuid.uuid4()}")
    db_session.add_all([store, agent])
    await db_session.commit()
    await db_session.refresh(store)
    await db_session.refresh(agent)

    sandbox_a = uuid.uuid4()
    sandbox_b = uuid.uuid4()
    session_a = JoySafeterSession(agent_id=agent.id, status="running", last_sandbox_id=sandbox_a)
    db_session.add(session_a)
    await db_session.commit()
    await db_session.refresh(session_a)

    session_b = JoySafeterSession(agent_id=agent.id, status="running", last_sandbox_id=sandbox_b)
    db_session.add(session_b)
    await db_session.commit()
    await db_session.refresh(session_b)

    db_session.add(
        JoySafeterSessionMemoryStore(
            session_id=session_a.id,
            store_id=store.id,
            access="read_write",
            mount_name="main",
        )
    )
    await db_session.commit()

    db_session.add(
        JoySafeterSessionMemoryStore(
            session_id=session_b.id,
            store_id=store.id,
            access="read_write",
            mount_name="renamed",
        )
    )
    await db_session.commit()
    return store.id, {sandbox_a: "runtime-a", sandbox_b: "runtime-b"}


async def _memory_store(db_session):
    store = JoySafeterMemoryStore(name=f"memory-entry-store-{uuid.uuid4()}", description="")
    db_session.add(store)
    await db_session.commit()
    await db_session.refresh(store)
    return store.id


@pytest.mark.asyncio
async def test_archive_memory_store_rejects_active_session_reference(db_session):
    store_id = await _mounted_store(db_session)

    with pytest.raises(AppError) as exc_info:
        await archive_memory_store(store_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_STORE_ACTIVE_SESSION_REFERENCE",
        "message": "Memory store is referenced by one or more active sessions.",
        "data": {"memory_store_id": str(store_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    store_row = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    assert store_row.archived_at is None


@pytest.mark.asyncio
async def test_delete_memory_store_rejects_active_session_reference(db_session):
    store_id = await _mounted_store(db_session)

    with pytest.raises(AppError) as exc_info:
        await delete_memory_store(store_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_STORE_ACTIVE_SESSION_REFERENCE",
        "message": "Memory store is referenced by one or more active sessions.",
        "data": {"memory_store_id": str(store_id)},
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }

    db_session.expire_all()
    store_row = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    assert store_row.id == store_id


@pytest.mark.asyncio
async def test_archived_memory_store_remains_readable_with_memories(db_session):
    store_id = await _memory_store(db_session)
    memory = await create_memory(
        store_id,
        CreateMemoryRequest(path="/runbook.md", content="read-only after archive"),
        view=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )
    store = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    store.archived_at = utc_now()
    await db_session.commit()

    store_response = await get_memory_store(store_id, db_session, _auth_ctx())
    assert store_response.id == store_id
    assert store_response.archived_at is not None

    memories = await list_memories(
        store_id,
        limit=20,
        after_id=None,
        path_prefix=None,
        depth=None,
        order_by="path",
        order="asc",
        view="full",
        db=db_session,
        auth_ctx=_auth_ctx(),
    )
    assert [item.id for item in memories.data] == [memory.id]
    assert memories.data[0].content == "read-only after archive"


@pytest.mark.asyncio
async def test_create_memory_rejects_archived_store_without_creating_row(db_session):
    store_id = await _memory_store(db_session)
    store = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    store.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await create_memory(
            store_id,
            CreateMemoryRequest(path="/new.md", content="new content"),
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_STORE_ARCHIVED",
        "message": "Memory store is archived",
        "data": {"memory_store_id": str(store_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    count = (
        await db_session.execute(
            select(JoySafeterMemory).where(
                JoySafeterMemory.store_id == store_id,
                JoySafeterMemory.path == "/new.md",
            )
        )
    ).scalar_one_or_none()
    assert count is None


@pytest.mark.asyncio
async def test_update_memory_rejects_archived_store_without_mutating_content(db_session):
    store_id = await _memory_store(db_session)
    memory = await create_memory(
        store_id,
        CreateMemoryRequest(path="/notes.txt", content="original"),
        view=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )
    store = (
        await db_session.execute(select(JoySafeterMemoryStore).where(JoySafeterMemoryStore.id == store_id))
    ).scalar_one()
    store.archived_at = utc_now()
    await db_session.commit()

    with pytest.raises(AppError) as exc_info:
        await update_memory(
            store_id,
            memory.id,
            UpdateMemoryRequest(content="changed"),
            path=None,
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_STORE_ARCHIVED",
        "message": "Memory store is archived",
        "data": {"memory_store_id": str(store_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
    db_session.expire_all()
    row = (await db_session.execute(select(JoySafeterMemory).where(JoySafeterMemory.id == memory.id))).scalar_one()
    assert row.content == "original"


@pytest.mark.asyncio
async def test_memory_update_broadcast_targets_store_id_not_session_local_mount_name(db_session, monkeypatch):
    store_id, owners = await _mounted_store_with_active_sandboxes(db_session)
    redis = _FakeRedis(owners)
    monkeypatch.setattr("app.joysafeter_shared.cache.redis.RedisClient.get_client", lambda: redis)

    await _broadcast_memory_update(store_id, "/notes.txt", "updated", "modified", db_session)

    published = sorted(redis.published, key=lambda item: item[0])
    assert [channel for channel, _ in published] == [
        "joysafeter:cmd:runtime-a",
        "joysafeter:cmd:runtime-b",
    ]
    payloads = [json.loads(payload) for _, payload in published]
    assert payloads == [
        {
            "type": "memory_update",
            "store_id": str(store_id),
            "relative_path": "/notes.txt",
            "content": "updated",
            "operation": "modified",
        },
        {
            "type": "memory_update",
            "store_id": str(store_id),
            "relative_path": "/notes.txt",
            "content": "updated",
            "operation": "modified",
        },
    ]
    assert all("store_mount_name" not in payload for payload in payloads)


@pytest.mark.asyncio
async def test_create_memory_path_conflict_returns_structured_error(db_session):
    store_id = await _memory_store(db_session)

    await create_memory(
        store_id,
        CreateMemoryRequest(path="/notes.txt", content="first"),
        view=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )

    with pytest.raises(AppError) as exc_info:
        await create_memory(
            store_id,
            CreateMemoryRequest(path="/notes.txt", content="second"),
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_PATH_CONFLICT",
        "message": "A memory already exists at path '/notes.txt'",
        "data": {"memory_store_id": str(store_id), "path": "/notes.txt"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_memory_invalid_path_returns_structured_validation_error(db_session):
    store_id = await _memory_store(db_session)

    with pytest.raises(AppError) as exc_info:
        await create_memory(
            store_id,
            SimpleNamespace(path="notes.txt", content="body"),
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "MEMORY_PATH_INVALID",
        "message": "Path must start with '/'",
        "data": {"path": "notes.txt", "max_bytes": 1024},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_create_memory_oversized_content_returns_structured_validation_error(db_session):
    store_id = await _memory_store(db_session)
    content = "x" * 102401

    with pytest.raises(AppError) as exc_info:
        await create_memory(
            store_id,
            SimpleNamespace(path="/large.txt", content=content),
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "MEMORY_CONTENT_TOO_LARGE",
        "message": "Content exceeds 102400 bytes (100 KB)",
        "data": {"memory_store_id": str(store_id), "size_bytes": 102401, "max_bytes": 102400},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_list_memories_invalid_order_returns_structured_validation_error(db_session):
    store_id = await _memory_store(db_session)

    with pytest.raises(AppError) as exc_info:
        await list_memories(
            store_id,
            limit=20,
            after_id=None,
            path_prefix=None,
            depth=None,
            order_by="bad_column",
            order="asc",
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=400) == {
        "code": "MEMORY_LIST_ORDER_INVALID",
        "message": "order_by must be one of: created_at, path, updated_at",
        "data": {"field": "order_by", "value": "bad_column", "allowed": ["created_at", "path", "updated_at"]},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
    }


@pytest.mark.asyncio
async def test_update_memory_precondition_mismatch_returns_structured_error(db_session):
    store_id = await _memory_store(db_session)
    memory = await create_memory(
        store_id,
        CreateMemoryRequest(path="/notes.txt", content="first"),
        view=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )

    with pytest.raises(AppError) as exc_info:
        await update_memory(
            store_id,
            memory.id,
            UpdateMemoryRequest(content="second", if_sha256="stale"),
            path=None,
            view=None,
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_PRECONDITION_FAILED",
        "message": f"SHA256 mismatch: expected stale, got {memory.content_sha256}",
        "data": {
            "memory_store_id": str(store_id),
            "memory_id": str(memory.id),
            "expected_sha256": "stale",
            "actual_sha256": memory.content_sha256,
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_delete_memory_precondition_mismatch_returns_structured_error(db_session):
    store_id = await _memory_store(db_session)
    memory = await create_memory(
        store_id,
        CreateMemoryRequest(path="/notes.txt", content="first"),
        view=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )

    with pytest.raises(AppError) as exc_info:
        await delete_memory(
            store_id,
            memory.id,
            expected_content_sha256="stale",
            db=db_session,
            auth_ctx=_auth_ctx(),
        )

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_PRECONDITION_FAILED",
        "message": f"SHA256 mismatch: expected stale, got {memory.content_sha256}",
        "data": {
            "memory_store_id": str(store_id),
            "memory_id": str(memory.id),
            "expected_sha256": "stale",
            "actual_sha256": memory.content_sha256,
        },
        "source": "api",
        "retryable": True,
        "user_action": "retry",
    }


@pytest.mark.asyncio
async def test_redact_memory_live_version_returns_structured_error(db_session):
    store_id = await _memory_store(db_session)
    memory = await create_memory(
        store_id,
        CreateMemoryRequest(path="/notes.txt", content="first"),
        view=None,
        db=db_session,
        auth_ctx=_auth_ctx(),
    )

    assert memory.memory_version_id is not None
    with pytest.raises(AppError) as exc_info:
        await redact_memory_version(store_id, memory.memory_version_id, db_session, _auth_ctx())

    assert await handled_app_error_payload(exc_info.value, status_code=409) == {
        "code": "MEMORY_LIVE_VERSION_REDACTION_FORBIDDEN",
        "message": "Cannot redact a live version. This version is the current version of a memory.",
        "data": {"memory_store_id": str(store_id), "memory_version_id": str(memory.memory_version_id)},
        "source": "api",
        "retryable": False,
        "user_action": "refresh",
    }
