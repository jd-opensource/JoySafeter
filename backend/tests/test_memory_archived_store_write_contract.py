import pytest

from app.joysafeter_domain.services.joysafeter_memory_service import (
    MemoryService,
    MemoryStoreArchived,
)
from app.joysafeter_shared.ids import MemoryId, MemoryStoreId


@pytest.mark.asyncio
async def test_memory_writes_to_archived_store_raise_not_silently_drop(db_session):
    # Reads treat archived stores as visible, so writes must fail loudly rather
    # than silently no-op (which loses an agent-runtime write with no signal).
    svc = MemoryService(db_session)
    store = await svc.create_store(name="notes", project_id=None)
    mem = await svc.create_memory(store.id, "a.md", "v1", project_id=None)
    assert mem is not None

    assert await svc.archive_store(store.id, project_id=None) is True

    with pytest.raises(MemoryStoreArchived):
        await svc.create_memory(store.id, "b.md", "x", project_id=None)

    with pytest.raises(MemoryStoreArchived):
        await svc.update_memory(store.id, mem.id, "v2", project_id=None)

    with pytest.raises(MemoryStoreArchived):
        await svc.delete_memory(store.id, mem.id, project_id=None)

    # The agent-runtime upsert path must also surface the archived store rather
    # than misclassifying the archived guard as a concurrent delete + recreate.
    with pytest.raises(MemoryStoreArchived):
        await svc.upsert_memory_from_agent(store.id, "a.md", "v3", project_id=None)


@pytest.mark.asyncio
async def test_memory_writes_to_missing_store_still_return_none(db_session):
    # A genuinely absent store is not the same as an archived one: writes return
    # None/False (not-found), they do not raise MemoryStoreArchived.
    svc = MemoryService(db_session)
    missing = MemoryStoreId.new()

    assert await svc.create_memory(missing, "a.md", "x", project_id=None) is None
    assert await svc.delete_memory(missing, MemoryId.new(), project_id=None) is False
