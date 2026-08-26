import logging
import re
import unicodedata
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.schemas.base import CursorPaginatedResponse as PaginatedResponse
from app.joysafeter_domain.schemas.joysafeter_memory import (
    MEMORY_MAX_CONTENT_BYTES,
    MEMORY_MAX_PATH_BYTES,
    CreateMemoryRequest,
    CreateMemoryStoreRequest,
    MemoryResponse,
    MemoryStoreResponse,
    MemoryVersionResponse,
    UpdateMemoryRequest,
    UpdateMemoryStoreRequest,
)
from app.joysafeter_domain.services.joysafeter_memory_service import (
    MemoryService,
    MemoryStoreLimitExceeded,
    PreconditionFailed,
)
from app.joysafeter_shared.common.app_errors import AppError, InvalidRequestError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.common.joysafeter_auth import (
    JoySafeterAuthContext,
    get_joysafeter_auth_context,
    require_joysafeter_write,
)
from app.joysafeter_shared.database import get_db
from app.joysafeter_shared.ids import (
    MemoryId,
    MemoryStoreId,
    MemoryVersionId,
    SandboxId,
    SessionId,
    as_uuid,
)

router = APIRouter(tags=["joysafeter-memory-stores"])

logger = logging.getLogger(__name__)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


async def _broadcast_memory_update(
    store_id: MemoryStoreId,
    path: str,
    content: str,
    operation: str,
    db: AsyncSession,
) -> None:
    """Broadcast a memory change to all running sandboxes via Redis.

    The orchestrator's CommandListener picks this up and fans it out to all
    sandboxes that have this store mounted, updating their FUSE caches in
    real time.

    Key: we must publish to the orchestrator instance that owns each sandbox,
    not to the API's own instance_id (they are different processes).
    """
    try:
        # Find all active sandbox owners that have this store mounted. Mount
        # names are session-local, so the Rust runtime must fan out by store_id
        # and translate to each subscriber's own mount_name.
        from sqlalchemy import text

        rows = await db.execute(
            text(
                "SELECT DISTINCT s.last_sandbox_id "
                "FROM joysafeter_session_memory_stores sm "
                "JOIN joysafeter_sessions s ON s.id = sm.session_id "
                "WHERE sm.store_id = :sid "
                "  AND s.last_sandbox_id IS NOT NULL "
                "  AND s.status NOT IN ('ended', 'error')"
            ),
            {"sid": as_uuid(store_id)},
        )
        active_rows = rows.all()
        if not active_rows:
            return  # No active session has this store mounted

        from app.joysafeter_shared.orchestrator_bridge.runtime_commands import publish_to_sandbox_owners_via_redis

        delivered = await publish_to_sandbox_owners_via_redis(
            [SandboxId.from_uuid(sandbox_id) for (sandbox_id,) in active_rows],
            command={
                "type": "memory_update",
                "store_id": str(as_uuid(store_id)),
                "relative_path": path,
                "content": content,
                "operation": operation,
            },
            boundary="memory_store_api",
            operation="broadcast_memory_update",
            failure_code="MEMORY_STORE_REDIS_UPDATE_PUBLISH_FAILED",
            failure_message="Redis memory update publish failed",
            data={"store_id": str(store_id), "relative_path": path},
        )
        if delivered:
            logger.debug("Broadcast memory_update to %s owner instance(s): %s", delivered, path)
    except Exception as e:
        logger.debug(f"Failed to broadcast memory_update: {e}")


def _memory_store_conflict_error(store_id: MemoryStoreId, exc: ValueError) -> AppError:
    message = str(exc)
    if message.startswith("Memory store is referenced by one or more active sessions"):
        return ResourceConflictError(
            code="MEMORY_STORE_ACTIVE_SESSION_REFERENCE",
            message=message,
            data={"memory_store_id": str(store_id)},
            retryable=True,
            user_action="retry",
        )
    return ResourceConflictError(
        code="MEMORY_STORE_CONFLICT",
        message=message,
        data={"memory_store_id": str(store_id)},
    )


def _memory_store_not_found_error(store_id: MemoryStoreId) -> AppError:
    return NotFoundError(
        code="MEMORY_STORE_NOT_FOUND",
        message="Memory store not found",
        data={"memory_store_id": str(store_id)},
        user_action="refresh",
    )


def _memory_store_archived_error(store_id: MemoryStoreId) -> AppError:
    return ResourceConflictError(
        code="MEMORY_STORE_ARCHIVED",
        message="Memory store is archived",
        data={"memory_store_id": str(store_id)},
        retryable=False,
        user_action="refresh",
    )


def _memory_not_found_error(store_id: MemoryStoreId, memory_id: MemoryId) -> AppError:
    return NotFoundError(
        code="MEMORY_NOT_FOUND",
        message="Memory not found",
        data={"memory_store_id": str(store_id), "memory_id": str(memory_id)},
        user_action="refresh",
    )


def _memory_version_not_found_error(store_id: MemoryStoreId, version_id: MemoryVersionId) -> AppError:
    return NotFoundError(
        code="MEMORY_VERSION_NOT_FOUND",
        message="Memory version not found",
        data={"memory_store_id": str(store_id), "version_id": str(version_id)},
        user_action="refresh",
    )


def _memory_metadata_invalid_error(message: str, data: dict[str, object]) -> AppError:
    return InvalidRequestError(
        code="MEMORY_METADATA_INVALID",
        message=message,
        data=data,
        user_action="fix_input",
    )


def _memory_path_invalid_error(message: str, *, path: str) -> AppError:
    return InvalidRequestError(
        code="MEMORY_PATH_INVALID",
        message=message,
        data={"path": path, "max_bytes": MEMORY_MAX_PATH_BYTES},
        user_action="fix_input",
    )


def _memory_precondition_error(
    *,
    store_id: MemoryStoreId,
    memory_id: MemoryId,
    expected_sha256: str,
    actual_sha256: str,
) -> AppError:
    return ResourceConflictError(
        code="MEMORY_PRECONDITION_FAILED",
        message=f"SHA256 mismatch: expected {expected_sha256}, got {actual_sha256}",
        data={
            "memory_store_id": str(store_id),
            "memory_id": str(memory_id),
            "expected_sha256": expected_sha256,
            "actual_sha256": actual_sha256,
        },
        retryable=True,
        user_action="retry",
    )


def _memory_precondition_exception_error(
    *,
    store_id: MemoryStoreId,
    memory_id: MemoryId,
    exc: PreconditionFailed,
) -> AppError:
    message = str(exc)
    match = re.match(r"^SHA256 mismatch: expected ([^,]+), got (.+)$", message)
    if match:
        expected_sha256, actual_sha256 = match.groups()
        return _memory_precondition_error(
            store_id=store_id,
            memory_id=memory_id,
            expected_sha256=expected_sha256,
            actual_sha256=actual_sha256,
        )
    return ResourceConflictError(
        code="MEMORY_PRECONDITION_FAILED",
        message=message,
        data={"memory_store_id": str(store_id), "memory_id": str(memory_id)},
        retryable=True,
        user_action="retry",
    )


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
        or cp == 0x110BD
        or cp == 0x110CD  # Kaithi number signs
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
        raise _memory_metadata_invalid_error(
            f"Metadata exceeds maximum of {_META_MAX_KEYS} keys (got {len(metadata)})",
            {"field": "metadata", "max_keys": _META_MAX_KEYS, "actual_keys": len(metadata)},
        )
    for key, value in metadata.items():
        if not isinstance(key, str):
            raise _memory_metadata_invalid_error(
                "Metadata keys must be strings",
                {"field": "metadata", "key": repr(key)},
            )
        if len(key) < _META_KEY_MIN_LEN or len(key) > _META_KEY_MAX_LEN:
            raise _memory_metadata_invalid_error(
                f"Metadata key length must be between {_META_KEY_MIN_LEN} and {_META_KEY_MAX_LEN} characters (key={key!r})",
                {
                    "field": "metadata",
                    "key": key,
                    "min_length": _META_KEY_MIN_LEN,
                    "max_length": _META_KEY_MAX_LEN,
                },
            )
        if not isinstance(value, str):
            raise _memory_metadata_invalid_error(
                f"Metadata values must be strings (key={key!r}, got {type(value).__name__})",
                {"field": "metadata", "key": key, "value_type": type(value).__name__},
            )
        if len(value) > _META_VALUE_MAX_LEN:
            raise _memory_metadata_invalid_error(
                f"Metadata value exceeds {_META_VALUE_MAX_LEN} characters (key={key!r})",
                {"field": "metadata", "key": key, "max_length": _META_VALUE_MAX_LEN, "actual_length": len(value)},
            )


# --- Path validation helpers ---


def _normalize_and_validate_path(path: str) -> str:
    """Apply Unicode NFC normalization and validate path constraints."""
    # Unicode NFC normalization
    path = unicodedata.normalize("NFC", path)

    if not path.startswith("/"):
        raise _memory_path_invalid_error("Path must start with '/'", path=path)
    if len(path.encode("utf-8")) > MEMORY_MAX_PATH_BYTES:
        raise _memory_path_invalid_error(f"Path exceeds {MEMORY_MAX_PATH_BYTES} bytes", path=path)
    segments = path.split("/")
    for segment in segments:
        if segment in (".", ".."):
            raise _memory_path_invalid_error("Path must not contain '.' or '..' segments", path=path)
    if "//" in path:
        raise _memory_path_invalid_error("Path must not contain '//'", path=path)
    if _CONTROL_CHAR_RE.search(path):
        raise _memory_path_invalid_error("Path must not contain control characters", path=path)
    for ch in path:
        if _is_unicode_format_char(ch):
            raise _memory_path_invalid_error("Path must not contain control or format characters", path=path)
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


async def _get_store_or_404(
    svc: MemoryService,
    store_id: MemoryStoreId,
    project_id: str | None,
    *,
    include_archived: bool = False,
):
    store = await svc.get_store(store_id, project_id=project_id, include_archived=include_archived)
    if not store:
        raise _memory_store_not_found_error(store_id)
    return store


async def _get_readable_store_or_404(svc: MemoryService, store_id: MemoryStoreId, project_id: str | None):
    return await _get_store_or_404(svc, store_id, project_id, include_archived=True)


async def _get_mutable_store_or_404(svc: MemoryService, store_id: MemoryStoreId, project_id: str | None):
    store = await _get_store_or_404(svc, store_id, project_id, include_archived=True)
    if store.archived_at is not None:
        raise _memory_store_archived_error(store_id)
    return store


# --- Store CRUD ---


@router.post("", status_code=201)
async def create_memory_store(
    req: CreateMemoryStoreRequest,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> MemoryStoreResponse:
    if req.metadata:
        _validate_metadata(req.metadata)
    svc = MemoryService(db)
    store = await svc.create_store(req.name, req.description, req.metadata, project_id=auth_ctx.project_id)
    return _store_to_response(store)


@router.get("")
async def list_memory_stores(
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[MemoryStoreId] = Query(None),
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[MemoryStoreResponse, MemoryStoreId]:
    svc = MemoryService(db)
    stores, has_more = await svc.list_stores(
        limit, after_id, project_id=auth_ctx.project_id, include_archived=include_archived
    )
    data = [_store_to_response(s) for s in stores]
    return PaginatedResponse[MemoryStoreResponse, MemoryStoreId](
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/{store_id}")
async def get_memory_store(
    store_id: MemoryStoreId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> MemoryStoreResponse:
    svc = MemoryService(db)
    store = await _get_readable_store_or_404(svc, store_id, auth_ctx.project_id)
    return _store_to_response(store)


@router.post("/{store_id}")
async def update_memory_store(
    store_id: MemoryStoreId,
    req: UpdateMemoryStoreRequest = Body(...),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> MemoryStoreResponse:
    svc = MemoryService(db)
    store = await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)

    # Partial metadata patching: merge incoming metadata with existing,
    # null values remove keys from the map.
    merged_metadata = None
    if req.metadata is not None:
        _validate_metadata({k: v for k, v in req.metadata.items() if v is not None})
        existing = dict(store.metadata_ or {})
        for key, value in req.metadata.items():
            if value is None:
                existing.pop(key, None)
            else:
                existing[key] = value
        merged_metadata = existing

    store = await svc.update_store(
        store_id,
        req.name,
        req.description,
        merged_metadata,
        project_id=auth_ctx.project_id,
    )
    if not store:
        raise _memory_store_not_found_error(store_id)
    return _store_to_response(store)


@router.delete("/{store_id}", status_code=200)
async def delete_memory_store(
    store_id: MemoryStoreId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = MemoryService(db)
    store = await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)
    response = _store_to_response(store)
    try:
        ok = await svc.delete_store(store_id, project_id=auth_ctx.project_id)
    except ValueError as exc:
        raise _memory_store_conflict_error(store_id, exc) from exc
    if not ok:
        raise _memory_store_not_found_error(store_id)
    return response.model_dump(mode="json")


@router.post("/{store_id}/archive")
async def archive_memory_store(
    store_id: MemoryStoreId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = MemoryService(db)
    await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)
    try:
        ok = await svc.archive_store(store_id, project_id=auth_ctx.project_id)
    except ValueError as exc:
        raise _memory_store_conflict_error(store_id, exc) from exc
    if not ok:
        raise _memory_store_not_found_error(store_id)
    return {"status": "archived"}


# --- Memory CRUD ---


@router.post("/{store_id}/memories", status_code=201)
async def create_memory(
    store_id: MemoryStoreId,
    req: CreateMemoryRequest = Body(...),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> MemoryResponse:
    svc = MemoryService(db)
    await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)

    # Unicode NFC path normalization and validation
    normalized_path = _normalize_and_validate_path(req.path)

    # Content size validation
    content_size = len(req.content.encode("utf-8"))
    if content_size > MEMORY_MAX_CONTENT_BYTES:
        raise InvalidRequestError(
            code="MEMORY_CONTENT_TOO_LARGE",
            message=f"Content exceeds {MEMORY_MAX_CONTENT_BYTES} bytes (100 KB)",
            data={"memory_store_id": str(store_id), "size_bytes": content_size, "max_bytes": MEMORY_MAX_CONTENT_BYTES},
            user_action="fix_input",
        )

    # Path conflict check
    existing = await svc.get_memory_by_path(store_id, normalized_path, project_id=auth_ctx.project_id)
    if existing:
        raise ResourceConflictError(
            code="MEMORY_PATH_CONFLICT",
            message=f"A memory already exists at path {normalized_path!r}",
            data={"memory_store_id": str(store_id), "path": normalized_path},
            user_action="fix_input",
        )

    try:
        mem = await svc.create_memory(store_id, normalized_path, req.content, project_id=auth_ctx.project_id)
    except MemoryStoreLimitExceeded as exc:
        raise ResourceConflictError(
            code="MEMORY_STORE_LIMIT_EXCEEDED",
            message=str(exc),
            data={"memory_store_id": str(store_id)},
            user_action="fix_input",
        ) from exc
    if not mem:
        raise _memory_store_not_found_error(store_id)
    await _broadcast_memory_update(store_id, mem.path, mem.content or "", "created", db)
    return _memory_to_response(mem, view=view)


@router.get("/{store_id}/memories")
async def list_memories(
    store_id: MemoryStoreId,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[MemoryId] = Query(None),
    path_prefix: Optional[str] = Query(None),
    depth: Optional[int] = Query(None, ge=1),
    order_by: str = Query("path"),
    order: str = Query("asc"),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[MemoryResponse, MemoryId]:
    # Validate order_by to prevent arbitrary column access
    allowed_order_by = {"path", "created_at", "updated_at"}
    if order_by not in allowed_order_by:
        raise InvalidRequestError(
            code="MEMORY_LIST_ORDER_INVALID",
            message=f"order_by must be one of: {', '.join(sorted(allowed_order_by))}",
            data={"field": "order_by", "value": order_by, "allowed": sorted(allowed_order_by)},
            user_action="fix_input",
        )
    if order not in ("asc", "desc"):
        raise InvalidRequestError(
            code="MEMORY_LIST_ORDER_INVALID",
            message="order must be 'asc' or 'desc'",
            data={"field": "order", "value": order, "allowed": ["asc", "desc"]},
            user_action="fix_input",
        )

    svc = MemoryService(db)
    await _get_readable_store_or_404(svc, store_id, auth_ctx.project_id)
    memories, has_more = await svc.list_memories(
        store_id,
        limit,
        after_id,
        path_prefix=path_prefix,
        order_by=order_by,
        order=order,
        project_id=auth_ctx.project_id,
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
    return PaginatedResponse[MemoryResponse, MemoryId](
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/{store_id}/memories/{memory_id}")
async def get_memory(
    store_id: MemoryStoreId,
    memory_id: MemoryId,
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> MemoryResponse:
    svc = MemoryService(db)
    await _get_readable_store_or_404(svc, store_id, auth_ctx.project_id)
    mem = await svc.get_memory(store_id, memory_id, project_id=auth_ctx.project_id)
    if not mem:
        raise _memory_not_found_error(store_id, memory_id)
    return _memory_to_response(mem, view=view)


@router.post("/{store_id}/memories/{memory_id}")
async def update_memory(
    store_id: MemoryStoreId,
    memory_id: MemoryId,
    req: UpdateMemoryRequest = Body(...),
    path: Optional[str] = Query(None),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> MemoryResponse:
    svc = MemoryService(db)
    await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)

    precondition_sha256 = req.precondition.get("content_sha256") if req.precondition is not None else None

    # Handle path move
    if path is not None:
        normalized_path = _normalize_and_validate_path(path)
        # Check for path conflict at target
        existing = await svc.get_memory_by_path(store_id, normalized_path, project_id=auth_ctx.project_id)
        if existing and existing.id != memory_id:
            raise ResourceConflictError(
                code="MEMORY_PATH_CONFLICT",
                message=f"A memory already exists at path {normalized_path!r}",
                data={"memory_store_id": str(store_id), "path": normalized_path},
                user_action="fix_input",
            )
        mem = await svc.get_memory(store_id, memory_id, project_id=auth_ctx.project_id)
        if not mem:
            raise _memory_not_found_error(store_id, memory_id)
        if precondition_sha256 is not None and mem.content_sha256 != precondition_sha256:
            raise _memory_precondition_error(
                store_id=store_id,
                memory_id=memory_id,
                expected_sha256=precondition_sha256,
                actual_sha256=mem.content_sha256,
            )
        # Move: update the path on the memory object
        mem.path = normalized_path
        from app.joysafeter_shared.utils.datetime import utc_now

        mem.updated_at = utc_now()
        await svc.db.commit()
        await svc.db.refresh(mem)
        # Now update content if provided
        if req.content is not None:
            try:
                mem = await svc.update_memory(
                    store_id,
                    memory_id,
                    req.content,
                    expected_sha256=None,
                    project_id=auth_ctx.project_id,
                )
            except PreconditionFailed as e:
                raise _memory_precondition_exception_error(store_id=store_id, memory_id=memory_id, exc=e) from e
            if not mem:
                raise _memory_not_found_error(store_id, memory_id)
        await _broadcast_memory_update(store_id, mem.path, mem.content or "", "modified", db)
        return _memory_to_response(mem, view=view)

    if req.content is None:
        # No content and no path move -- nothing to update
        mem = await svc.get_memory(store_id, memory_id, project_id=auth_ctx.project_id)
        if not mem:
            raise _memory_not_found_error(store_id, memory_id)
        return _memory_to_response(mem, view=view)

    try:
        mem = await svc.update_memory(
            store_id,
            memory_id,
            req.content,
            expected_sha256=precondition_sha256,
            project_id=auth_ctx.project_id,
        )
    except PreconditionFailed as e:
        raise _memory_precondition_exception_error(store_id=store_id, memory_id=memory_id, exc=e) from e
    if not mem:
        raise _memory_not_found_error(store_id, memory_id)
    await _broadcast_memory_update(store_id, mem.path, mem.content or "", "modified", db)
    return _memory_to_response(mem, view=view)


@router.delete("/{store_id}/memories/{memory_id}", status_code=200)
async def delete_memory(
    store_id: MemoryStoreId,
    memory_id: MemoryId,
    expected_content_sha256: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = MemoryService(db)
    await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)
    mem = await svc.get_memory(store_id, memory_id, project_id=auth_ctx.project_id)
    if not mem:
        raise _memory_not_found_error(store_id, memory_id)

    # Precondition check via query param
    if expected_content_sha256 is not None:
        if mem.content_sha256 != expected_content_sha256:
            raise _memory_precondition_error(
                store_id=store_id,
                memory_id=memory_id,
                expected_sha256=expected_content_sha256,
                actual_sha256=mem.content_sha256,
            )

    response = _memory_to_response(mem, view="full")
    mem_path = mem.path
    ok = await svc.delete_memory(store_id, memory_id, project_id=auth_ctx.project_id)
    if not ok:
        raise _memory_not_found_error(store_id, memory_id)
    await _broadcast_memory_update(store_id, mem_path, "", "deleted", db)
    return response.model_dump(mode="json")


# --- Memory Versions ---


@router.get("/{store_id}/memory_versions")
async def list_memory_versions(
    store_id: MemoryStoreId,
    limit: int = Query(20, ge=1, le=100),
    after_id: Optional[MemoryVersionId] = Query(None),
    memory_id: Optional[MemoryId] = Query(None),
    session_id: Optional[SessionId] = Query(None),
    operation: Optional[str] = Query(None),
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> PaginatedResponse[MemoryVersionResponse, MemoryVersionId]:
    svc = MemoryService(db)
    await _get_readable_store_or_404(svc, store_id, auth_ctx.project_id)
    versions, has_more = await svc.list_versions(
        store_id,
        limit,
        after_id,
        memory_id=memory_id,
        session_id=session_id,
        operation=operation,
        project_id=auth_ctx.project_id,
    )
    data = [_version_to_response(v, view=view) for v in versions]
    return PaginatedResponse[MemoryVersionResponse, MemoryVersionId](
        data=data,
        has_more=has_more,
        first_id=data[0].id if data else None,
        last_id=data[-1].id if data else None,
    )


@router.get("/{store_id}/memory_versions/{version_id}")
async def get_memory_version(
    store_id: MemoryStoreId,
    version_id: MemoryVersionId,
    view: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(get_joysafeter_auth_context),
) -> MemoryVersionResponse:
    svc = MemoryService(db)
    await _get_readable_store_or_404(svc, store_id, auth_ctx.project_id)
    ver = await svc.get_version(store_id, version_id, project_id=auth_ctx.project_id)
    if not ver:
        raise _memory_version_not_found_error(store_id, version_id)
    return _version_to_response(ver, view=view)


@router.post("/{store_id}/memory_versions/{version_id}/redact")
async def redact_memory_version(
    store_id: MemoryStoreId,
    version_id: MemoryVersionId,
    db: AsyncSession = Depends(get_db),
    auth_ctx: JoySafeterAuthContext = Depends(require_joysafeter_write),
) -> dict:
    svc = MemoryService(db)
    await _get_mutable_store_or_404(svc, store_id, auth_ctx.project_id)
    ver = await svc.get_version(store_id, version_id, project_id=auth_ctx.project_id)
    if not ver:
        raise _memory_version_not_found_error(store_id, version_id)

    # Block redaction if this is the live (current) version of any memory
    is_live = await svc.is_live_version(store_id, version_id, project_id=auth_ctx.project_id)
    if is_live:
        raise ResourceConflictError(
            code="MEMORY_LIVE_VERSION_REDACTION_FORBIDDEN",
            message="Cannot redact a live version. This version is the current version of a memory.",
            data={"memory_store_id": str(store_id), "memory_version_id": str(version_id)},
            user_action="refresh",
        )

    ok = await svc.redact_version(store_id, version_id, project_id=auth_ctx.project_id)
    if not ok:
        raise _memory_version_not_found_error(store_id, version_id)
    return {"status": "redacted"}
