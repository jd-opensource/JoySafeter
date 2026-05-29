import asyncio
import json
import re
import unicodedata
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
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
    MEMORY_MAX_CONTENT_BYTES,
    MEMORY_MAX_PATH_BYTES,
)
from app.conductor.schemas.common import PaginatedResponse
from app.conductor.services.memory_service import MemoryService, PreconditionFailed

router = APIRouter(tags=["conductor-memory-stores"])

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _is_unicode_format_char(ch: str) -> bool:
    """Check if a character is a Unicode format character that should be rejected
    in memory paths. Matches the Rust is_unicode_format_char logic."""
    cp = ord(ch)
    return (
        cp == 0x00AD  # SOFT HYPHEN
        or 0x0600 <= cp <= 0x0605  # Arabic format chars
        or cp == 0x061C  # ARABIC LETTER MARK
        or cp == 0x06DD  # ARABIC END OF AYAH
        or cp == 0x070F  # SYRIAC ABBREVIATION MARK
        or 0x0890 <= cp <= 0x0891  # Arabic format chars
        or cp == 0x08E2  # ARABIC DISPUTED END OF AYAH
        or cp == 0x180E  # MONGOLIAN VOWEL SEPARATOR
        or 0x200B <= cp <= 0x200F  # Zero-width and directional marks
        or 0x202A <= cp <= 0x202E  # Directional formatting
        or 0x2060 <= cp <= 0x2064  # Word joiner, invisible chars
        or 0x2066 <= cp <= 0x2069  # Directional isolates
        or cp == 0xFEFF  # BOM / ZERO WIDTH NO-BREAK SPACE
        or 0xFFF9 <= cp <= 0xFFFB  # Interlinear annotations
        or cp == 0x110BD or cp == 0x110CD  # Kaithi number signs
        or 0x13430 <= cp <= 0x1343F  # Egyptian hieroglyph format
        or 0x1BCA0 <= cp <= 0x1BCA3  # Shorthand format controls
        or 0x1D173 <= cp <= 0x1D17A  # Musical symbol formatting
        or cp == 0xE0001  # LANGUAGE TAG
        or 0xE0020 <= cp <= 0xE007F  # TAG characters
    )

# --- Metadata validation helpers ---

_META_MAX_KEYS = 16
_META_KEY_MIN_LEN = 1
_META_KEY_MAX_LEN = 64
_META_VALUE_MAX_LEN = 512


def _validate_metadata(metadata: dict) -> None:
    """Validate metadata constraints: max 16 keys, keys 1-64 chars, values max 512 chars, all string values."""
    if len(metadata) > _META_MAX_KEYS:
        raise HTTPException(
            400,
            f"Metadata exceeds maximum of {_META_MAX_KEYS} keys (got {len(metadata)})",
        )
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise HTTPException(400, "Metadata keys must be strings")
        if len(key) < _META_KEY_MIN_LEN or len(key) > _META_KEY_MAX_LEN:
            raise HTTPException(
                400,
                f"Metadata key length must be between {_META_KEY_MIN_LEN} and {_META_KEY_MAX_LEN} characters (key={key!r})",
            )
        if not isinstance(value, str):
            raise HTTPException(
                400,
                f"Metadata values must be strings (key={key!r}, got {type(value).__name__})",
            )
        if len(value) > _META_VALUE_MAX_LEN:
            raise HTTPException(
                400,
                f"Metadata value exceeds {_META_VALUE_MAX_LEN} characters (key={key!r})",
            )


# --- Path validation helpers ---


def _normalize_and_validate_path(path: str) -> str:
    """Apply Unicode NFC normalization and validate path constraints."""
    # Unicode NFC normalization
    path = unicodedata.normalize("NFC", path)

    if not path.startswith("/"):
        raise HTTPException(400, "Path must start with '/'")
    if len(path.encode("utf-8")) > MEMORY_MAX_PATH_BYTES:
        raise HTTPException(400, f"Path exceeds {MEMORY_MAX_PATH_BYTES} bytes")
    segments = path.split("/")
    for segment in segments:
        if segment in (".", ".."):
            raise HTTPException(400, "Path must not contain '.' or '..' segments")
    if "//" in path:
        raise HTTPException(400, "Path must not contain '//'")
    if _CONTROL_CHAR_RE.search(path):
        raise HTTPException(400, "Path must not contain control characters")
    for ch in path:
        if _is_unicode_format_char(ch):
            raise HTTPException(400, "Path must not contain control or format characters")
    return path


# --- Response builders ---


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


def _memory_to_response(mem, view: Optional[str] = None) -> MemoryResponse:
    return MemoryResponse(
        id=mem.id,
        memory_store_id=mem.store_id,
        path=mem.path,
        content=mem.content if view == "full" else None,
        content_sha256=mem.content_sha256,
        content_size_bytes=mem.size_bytes,
        memory_version_id=mem.current_version_id,
        created_at=mem.created_at,
        updated_at=mem.updated_at,
    )


def _version_to_response(ver, view: Optional[str] = None) -> MemoryVersionResponse:
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
        content=ver.content if view == "full" else None,
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
    if req.metadata:
        _validate_metadata(req.metadata)
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
    store = await svc.get_store(store_id)
    if not store:
        raise HTTPException(404, "Memory store not found")

    # Partial metadata patching: merge incoming metadata with existing,
    # null values remove keys from the map.
    merged_metadata = None
    if req.metadata is not None:
        _validate_metadata(
            {k: v for k, v in req.metadata.items() if v is not None}
        )
        existing = dict(store.metadata_ or {})
        for key, value in req.metadata.items():
            if value is None:
                existing.pop(key, None)
            else:
                existing[key] = value
        merged_metadata = existing

    store = await svc.update_store(store_id, req.name, req.description, merged_metadata)
    if not store:
        raise HTTPException(404, "Memory store not found")
    return _store_to_response(store)


@router.delete("/{store_id}", status_code=200)
async def delete_memory_store(
    store_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> dict:
    svc = MemoryService(db)
    store = await svc.get_store(store_id)
    if not store:
        raise HTTPException(404, "Memory store not found")
    response = _store_to_response(store)
    ok = await svc.delete_store(store_id)
    if not ok:
        raise HTTPException(404, "Memory store not found")
    return response.model_dump(mode="json")


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
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    svc = MemoryService(db)
    store = await svc.get_store(store_id)
    if not store:
        raise HTTPException(404, "Memory store not found")

    # Unicode NFC path normalization and validation
    normalized_path = _normalize_and_validate_path(req.path)

    # Content size validation
    if len(req.content.encode("utf-8")) > MEMORY_MAX_CONTENT_BYTES:
        raise HTTPException(
            400, f"Content exceeds {MEMORY_MAX_CONTENT_BYTES} bytes (100 KB)"
        )

    # Path conflict check
    existing = await svc.get_memory_by_path(store_id, normalized_path)
    if existing:
        raise HTTPException(409, f"A memory already exists at path {normalized_path!r}")

    mem = await svc.create_memory(store_id, normalized_path, req.content)
    return _memory_to_response(mem, view=view)


@router.get("/{store_id}/memories")
async def list_memories(
    store_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    path_prefix: Optional[str] = Query(None),
    depth: Optional[int] = Query(None, ge=1),
    order_by: str = Query("path"),
    order: str = Query("asc"),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryResponse]:
    # Validate order_by to prevent arbitrary column access
    allowed_order_by = {"path", "created_at", "updated_at"}
    if order_by not in allowed_order_by:
        raise HTTPException(
            400, f"order_by must be one of: {', '.join(sorted(allowed_order_by))}"
        )
    if order not in ("asc", "desc"):
        raise HTTPException(400, "order must be 'asc' or 'desc'")

    svc = MemoryService(db)
    memories, has_more = await svc.list_memories(
        store_id, limit, after_id,
        path_prefix=path_prefix,
        order_by=order_by,
        order=order,
    )

    # Apply depth filter (hierarchical view): count segments relative to prefix
    if depth is not None and path_prefix is not None:
        prefix_depth = path_prefix.rstrip("/").count("/")
        filtered = []
        for m in memories:
            mem_depth = m.path.rstrip("/").count("/") - prefix_depth
            if mem_depth <= depth:
                filtered.append(m)
        memories = filtered

    data = [_memory_to_response(m, view=view) for m in memories]
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
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    svc = MemoryService(db)
    mem = await svc.get_memory(store_id, memory_id)
    if not mem:
        raise HTTPException(404, "Memory not found")
    return _memory_to_response(mem, view=view)


@router.post("/{store_id}/memories/{memory_id}")
async def update_memory(
    store_id: uuid.UUID,
    memory_id: uuid.UUID,
    req: UpdateMemoryRequest,
    path: Optional[str] = Query(None),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> MemoryResponse:
    svc = MemoryService(db)

    # Handle precondition: support both legacy if_sha256 and new precondition object
    precondition_sha256 = req.if_sha256
    if req.precondition is not None:
        precondition_sha256 = req.precondition.get("content_sha256")

    # Handle path move
    if path is not None:
        normalized_path = _normalize_and_validate_path(path)
        # Check for path conflict at target
        existing = await svc.get_memory_by_path(store_id, normalized_path)
        if existing and existing.id != memory_id:
            raise HTTPException(
                409, f"A memory already exists at path {normalized_path!r}"
            )
        mem = await svc.get_memory(store_id, memory_id)
        if not mem:
            raise HTTPException(404, "Memory not found")
        if precondition_sha256 is not None and mem.content_sha256 != precondition_sha256:
            raise HTTPException(
                409,
                f"SHA256 mismatch: expected {precondition_sha256}, got {mem.content_sha256}",
            )
        # Move: update the path on the memory object
        mem.path = normalized_path
        from app.utils.datetime import utc_now
        mem.updated_at = utc_now()
        await svc.db.commit()
        await svc.db.refresh(mem)
        # Now update content if provided
        if req.content is not None:
            try:
                mem = await svc.update_memory(
                    store_id, memory_id, req.content, if_sha256=None
                )
            except PreconditionFailed as e:
                raise HTTPException(409, str(e))
            if not mem:
                raise HTTPException(404, "Memory not found")
        return _memory_to_response(mem, view=view)

    if req.content is None:
        # No content and no path move -- nothing to update
        mem = await svc.get_memory(store_id, memory_id)
        if not mem:
            raise HTTPException(404, "Memory not found")
        return _memory_to_response(mem, view=view)

    try:
        mem = await svc.update_memory(
            store_id, memory_id, req.content, if_sha256=precondition_sha256
        )
    except PreconditionFailed as e:
        raise HTTPException(409, str(e))
    if not mem:
        raise HTTPException(404, "Memory not found")
    return _memory_to_response(mem, view=view)


@router.delete("/{store_id}/memories/{memory_id}", status_code=200)
async def delete_memory(
    store_id: uuid.UUID,
    memory_id: uuid.UUID,
    expected_content_sha256: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = MemoryService(db)
    mem = await svc.get_memory(store_id, memory_id)
    if not mem:
        raise HTTPException(404, "Memory not found")

    # Precondition check via query param
    if expected_content_sha256 is not None:
        if mem.content_sha256 != expected_content_sha256:
            raise HTTPException(
                409,
                f"SHA256 mismatch: expected {expected_content_sha256}, got {mem.content_sha256}",
            )

    response = _memory_to_response(mem, view="full")
    ok = await svc.delete_memory(store_id, memory_id)
    if not ok:
        raise HTTPException(404, "Memory not found")
    return response.model_dump(mode="json")


# --- Memory Versions ---

@router.get("/{store_id}/memory_versions")
async def list_memory_versions(
    store_id: uuid.UUID,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[uuid.UUID] = Query(None),
    memory_id: Optional[uuid.UUID] = Query(None),
    session_id: Optional[uuid.UUID] = Query(None),
    operation: Optional[str] = Query(None),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[MemoryVersionResponse]:
    svc = MemoryService(db)
    versions, has_more = await svc.list_versions(
        store_id, limit, after_id,
        memory_id=memory_id,
        session_id=session_id,
        operation=operation,
    )
    data = [_version_to_response(v, view=view) for v in versions]
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
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> MemoryVersionResponse:
    svc = MemoryService(db)
    ver = await svc.get_version(store_id, version_id)
    if not ver:
        raise HTTPException(404, "Memory version not found")
    return _version_to_response(ver, view=view)


@router.post("/{store_id}/memory_versions/{version_id}/redact")
async def redact_memory_version(
    store_id: uuid.UUID,
    version_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict:
    svc = MemoryService(db)
    ver = await svc.get_version(store_id, version_id)
    if not ver:
        raise HTTPException(404, "Memory version not found")

    # Block redaction if this is the live (current) version of any memory
    is_live = await svc.is_live_version(store_id, version_id)
    if is_live:
        raise HTTPException(
            409,
            "Cannot redact a live version. This version is the current version of a memory.",
        )

    ok = await svc.redact_version(store_id, version_id)
    if not ok:
        raise HTTPException(404, "Memory version not found")
    return {"status": "redacted"}


# --- SSE Event Stream ---

@router.get("/{store_id}/events/stream")
async def memory_store_event_stream(
    store_id: uuid.UUID,
    request: Request,
    types: Optional[list[str]] = Query(None, alias="types[]"),
    db: AsyncSession = Depends(get_db),
):
    """SSE endpoint for real-time memory store event streaming.

    Supports ?types[] query param to filter by event types (e.g. created, modified, deleted).
    """
    svc = MemoryService(db)
    store = await svc.get_store(store_id)
    if not store:
        raise HTTPException(404, "Memory store not found")

    from app.conductor.lifespan import get_memory_subscribers

    subscribers = get_memory_subscribers()

    async def event_generator():
        if not subscribers:
            yield 'data: {"type": "error", "message": "Memory subscribers not available"}\n\n'
            return

        q: asyncio.Queue = asyncio.Queue()

        # Register a lightweight listener that puts events into our queue
        original_notify = subscribers.notify_peers

        async def _intercept_notify(
            sid: uuid.UUID, source_session_id: uuid.UUID, change_type: str, path: str
        ) -> int:
            if sid == store_id:
                event_data = {
                    "type": change_type,
                    "store_id": str(sid),
                    "path": path,
                }
                await q.put(event_data)
            return await original_notify(sid, source_session_id, change_type, path)

        subscribers.notify_peers = _intercept_notify
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    # Apply types filter
                    if types and event.get("type") not in types:
                        continue
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            subscribers.notify_peers = original_notify

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
