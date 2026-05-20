import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.conductor.schemas.memory import (
    CreateMemoryRequest,
    CreateMemoryStoreRequest,
    MemoryResponse,
    MemoryStoreResponse,
    MemoryVersionResponse,
    UpdateMemoryRequest,
    UpdateMemoryStoreRequest,
)
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.memory_service import MemoryService, PreconditionFailed

router = APIRouter(tags=["conductor-memory-stores"])


def _store_to_response(store) -> MemoryStoreResponse:
    return MemoryStoreResponse(
        id=store.id,
        name=store.name,
        description=store.description,
        metadata=store.metadata_,
        created_at=store.created_at,
        updated_at=store.updated_at,
        archived_at=store.archived_at,
    )


def _memory_to_response(mem) -> MemoryResponse:
    return MemoryResponse(
        id=mem.id,
        memory_store_id=mem.store_id,
        path=mem.path,
        content=mem.content,
        content_sha256=mem.content_sha256,
        content_size_bytes=mem.size_bytes,
        memory_version_id=mem.current_version_id,
        created_at=mem.created_at,
        updated_at=mem.updated_at,
    )


def _version_to_response(ver) -> MemoryVersionResponse:
    created_by = None
    if ver.session_id:
        created_by = {"type": "session_actor", "session_id": str(ver.session_id)}
    elif ver.api_key_id:
        created_by = {"type": "api_actor", "api_key_id": ver.api_key_id}
    return MemoryVersionResponse(
        id=ver.id,
        memory_store_id=ver.store_id,
        memory_id=ver.memory_id,
        operation=ver.operation,
        path=ver.path,
        content=ver.content,
        content_sha256=ver.content_sha256,
        content_size_bytes=ver.content_size_bytes,
        created_by=created_by,
        created_at=ver.created_at,
        redacted_at=ver.redacted_at,
        redacted_by=ver.redacted_by,
    )


# --- Store CRUD ---

@router.post("", status_code=201)
async def create_memory_store(
    req: CreateMemoryStoreRequest, db: AsyncSession = Depends(get_db)
) -> MemoryStoreResponse:
    svc = MemoryService(db)
    store = await svc.create_store(req.name, req.description, req.metadata)
    return _store_to_response(store)


@router.get("")
async def list_memory_stores(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryStoreResponse]:
    svc = MemoryService(db)
    stores, has_more = await svc.list_stores(limit, after_id)
    data = [_store_to_response(s) for s in stores]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{store_id}")
async def get_memory_store(
    store_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> MemoryStoreResponse:
    svc = MemoryService(db)
    store = await svc.get_store(store_id)
    if not store:
        raise HTTPException(404, "Memory store not found")
    return _store_to_response(store)


@router.post("/{store_id}")
async def update_memory_store(
    store_id: uuid.UUID,
    req: UpdateMemoryStoreRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryStoreResponse:
    svc = MemoryService(db)
    store = await svc.update_store(store_id, req.name, req.description, req.metadata)
    if not store:
        raise HTTPException(404, "Memory store not found")
    return _store_to_response(store)


@router.delete("/{store_id}", status_code=204)
async def delete_memory_store(
    store_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> None:
    svc = MemoryService(db)
    ok = await svc.delete_store(store_id)
    if not ok:
        raise HTTPException(404, "Memory store not found")


@router.post("/{store_id}/archive")
async def archive_memory_store(
    store_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = MemoryService(db)
    ok = await svc.archive_store(store_id)
    if not ok:
        raise HTTPException(404, "Memory store not found")
    return {"status": "archived"}


# --- Memory CRUD ---

@router.post("/{store_id}/memories", status_code=201)
async def create_memory(
    store_id: uuid.UUID,
    req: CreateMemoryRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    svc = MemoryService(db)
    store = await svc.get_store(store_id)
    if not store:
        raise HTTPException(404, "Memory store not found")
    mem = await svc.create_memory(store_id, req.path, req.content)
    return _memory_to_response(mem)


@router.get("/{store_id}/memories")
async def list_memories(
    store_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryResponse]:
    svc = MemoryService(db)
    memories, has_more = await svc.list_memories(store_id, limit, after_id)
    data = [_memory_to_response(m) for m in memories]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{store_id}/memories/{memory_id}")
async def get_memory(
    store_id: uuid.UUID,
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    svc = MemoryService(db)
    mem = await svc.get_memory(store_id, memory_id)
    if not mem:
        raise HTTPException(404, "Memory not found")
    return _memory_to_response(mem)


@router.post("/{store_id}/memories/{memory_id}")
async def update_memory(
    store_id: uuid.UUID,
    memory_id: uuid.UUID,
    req: UpdateMemoryRequest,
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    svc = MemoryService(db)
    try:
        mem = await svc.update_memory(store_id, memory_id, req.content, if_sha256=req.if_sha256)
    except PreconditionFailed as e:
        raise HTTPException(412, str(e))
    if not mem:
        raise HTTPException(404, "Memory not found")
    return _memory_to_response(mem)


@router.delete("/{store_id}/memories/{memory_id}", status_code=204)
async def delete_memory(
    store_id: uuid.UUID,
    memory_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> None:
    svc = MemoryService(db)
    ok = await svc.delete_memory(store_id, memory_id)
    if not ok:
        raise HTTPException(404, "Memory not found")


# --- Memory Versions ---

@router.get("/{store_id}/memory_versions")
async def list_memory_versions(
    store_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryVersionResponse]:
    svc = MemoryService(db)
    versions, has_more = await svc.list_versions(store_id, limit, after_id)
    data = [_version_to_response(v) for v in versions]
    return PaginatedResponse(
        data=data,
        has_more=has_more,
        first_id=str(data[0].id) if data else None,
        last_id=str(data[-1].id) if data else None,
    )


@router.get("/{store_id}/memory_versions/{version_id}")
async def get_memory_version(
    store_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> MemoryVersionResponse:
    svc = MemoryService(db)
    ver = await svc.get_version(store_id, version_id)
    if not ver:
        raise HTTPException(404, "Memory version not found")
    return _version_to_response(ver)


@router.post("/{store_id}/memory_versions/{version_id}/redact")
async def redact_memory_version(
    store_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = MemoryService(db)
    ok = await svc.redact_version(store_id, version_id)
    if not ok:
        raise HTTPException(404, "Memory version not found")
    return {"status": "redacted"}
