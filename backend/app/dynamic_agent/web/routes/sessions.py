"""Session routes for web visualization.
Uses real database data.
"""

from datetime import datetime, timezone

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from app.dynamic_agent.storage.persistence.daos.session_dao import SessionDAO
from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO
from app.dynamic_agent.web.models import (
    ChatMessageResponse,
    SessionDetailsResponse,
    SessionListResponse,
    SessionResponse,
    TaskBasicResponse,
)

router = APIRouter(prefix="/users/{user_id}/sessions", tags=["sessions"])


# Dependency to get database pool
async def get_db_pool() -> asyncpg.Pool:
    from app.dynamic_agent.main import init_storage

    try:
        # storage = get_storage_manager()
        storage = await init_storage()
        pool = storage.backend.pool
        return pool  # type: ignore[no-any-return]
    except RuntimeError:
        # Storage not initialized yet
        raise HTTPException(status_code=500, detail="Storage manager not initialized")


@router.get(
    "",
    response_model=SessionListResponse,
    summary="Get user sessions",
)
async def get_user_sessions(
    user_id: str,
    limit: int = Query(10, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    try:
        logger.info(f"📋 Getting sessions for user: {user_id}")

        # Use real database
        session_dao = SessionDAO(pool)
        sessions_data, total = await session_dao.list_user_sessions(user_id, limit, offset)

        # Convert to response models
        sessions = []
        for s in sessions_data:
            # Get first message as title
            title = f"Session {s['session_id'][-8:]}"

            # Convert datetime to milliseconds timestamp if needed
            # Database stores UTC time without timezone info, so we need to treat it as UTC
            created_at = s["created_at"]
            if isinstance(created_at, str):
                dt = datetime.fromisoformat(created_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                created_at = int(dt.timestamp() * 1000)
            elif hasattr(created_at, "timestamp"):
                # asyncpg returns naive datetime, treat as UTC
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)
                created_at = int(created_at.timestamp() * 1000)

            updated_at = s["updated_at"]
            if isinstance(updated_at, str):
                dt = datetime.fromisoformat(updated_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                updated_at = int(dt.timestamp() * 1000)
            elif hasattr(updated_at, "timestamp"):
                # asyncpg returns naive datetime, treat as UTC
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                updated_at = int(updated_at.timestamp() * 1000)

            sessions.append(
                SessionResponse(
                    id=s["session_id"],
                    user_id=s["user_id"],
                    title=title,
                    created_at=created_at,
                    updated_at=updated_at,
                    task_count=s.get("message_count", 0),  # Use message_count as task_count
                    mode=s.get("mode"),  # Add mode from session metadata
                )
            )

        return SessionListResponse(
            user_id=user_id,
            sessions=sessions,
            total_count=total,
        )
    except Exception as e:
        logger.error(f"❌ Error getting sessions: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{session_id}/history",
    summary="Get session message history",
)
async def get_session_history(
    user_id: str,
    session_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    try:
        logger.info(f"📜 Getting session history: user={user_id}, session={session_id}, limit={limit}, offset={offset}")

        # Load session context
        session_dao = SessionDAO(pool)
        context = await session_dao.load_context(session_id)

        if not context:
            return {
                "user_id": user_id,
                "session_id": session_id,
                "total_count": 0,
                "offset": offset,
                "limit": limit,
                "messages": [],
            }

        if context.user_id != user_id:
            raise HTTPException(status_code=404, detail="Session not found")

        # Get all messages
        all_messages = context.messages or []
        total_count = len(all_messages)

        # Apply pagination
        paginated_messages = all_messages[offset : offset + limit]

        # Convert messages and lookup task_id for user messages
        from app.dynamic_agent.storage.persistence.daos.task_dao import TaskDAO

        task_dao = TaskDAO(pool)

        messages = []
        for msg in paginated_messages:
            task_id = None

            # For user messages, lookup task_id from tasks table by message_id
            if msg.get("role") == "user" and msg.get("message_id"):
                message_id = msg.get("message_id")
                if message_id is not None and isinstance(message_id, int):
                    task_id = await task_dao.get_task_id_by_message_id(message_id)
                else:
                    task_id = None

            messages.append(
                ChatMessageResponse(
                    id=str(msg.get("message_id", "")),
                    session_id=session_id,
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    timestamp=int(msg.get("timestamp", 0)) if isinstance(msg.get("timestamp"), (int, float)) else 0,
                    task_id=task_id,
                )
            )

        return {
            "user_id": user_id,
            "session_id": session_id,
            "total_count": total_count,
            "offset": offset,
            "limit": limit,
            "messages": messages,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting session history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/{session_id}",
    response_model=SessionDetailsResponse,
    summary="Get session details",
)
async def get_session_details(
    user_id: str,
    session_id: str,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    try:
        logger.info(f"📖 Getting session details: user={user_id}, session={session_id}")

        # Load session context
        session_dao = SessionDAO(pool)
        context = await session_dao.load_context(session_id)

        if not context or context.user_id != user_id:
            raise HTTPException(status_code=404, detail="Session not found")

        # Convert messages
        messages = []
        for msg in context.messages[-50:]:  # Last 50 messages
            # Convert timestamp to milliseconds
            timestamp = msg.get("timestamp", "")
            if isinstance(timestamp, str) and timestamp:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    timestamp_ms = int(dt.timestamp() * 1000)
                except ValueError:
                    timestamp_ms = 0
            elif hasattr(timestamp, "timestamp"):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                timestamp_ms = int(timestamp.timestamp() * 1000)
            elif isinstance(timestamp, (int, float)):
                # Already a timestamp, convert to ms if needed
                timestamp_ms = int(timestamp * 1000) if timestamp < 10000000000 else int(timestamp)
            else:
                timestamp_ms = 0

            messages.append(
                ChatMessageResponse(
                    id=str(msg.get("message_id", "")),
                    session_id=session_id,
                    role=msg.get("role", "user"),
                    content=msg.get("content", ""),
                    timestamp=timestamp_ms,
                )
            )

        # Get tasks
        task_dao = TaskDAO(pool)
        tasks_result = await task_dao.get_tasks_by_session(session_id)
        # get_tasks_by_session returns tuple[List[TaskResponse], int]
        tasks_data = tasks_result[0] if isinstance(tasks_result, tuple) and len(tasks_result) > 0 else []

        tasks = []
        for t in tasks_data:
            tasks.append(
                TaskBasicResponse(
                    id=str(t.id),
                    session_id=str(t.session_id),
                    user_input=t.user_input,
                    status=t.status.value,
                    created_at=t.created_at.isoformat(),
                    updated_at=t.updated_at.isoformat(),
                    completed_at=t.completed_at.isoformat() if t.completed_at else None,
                    result_summary=t.result_summary,
                    metadata=t.metadata,
                )
            )

        # Convert timestamps to milliseconds
        created_at = context.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        created_at_ms = int(created_at.timestamp() * 1000)

        updated_at = context.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        updated_at_ms = int(updated_at.timestamp() * 1000)

        # Extract mode from session metadata
        mode = context.metadata.get("mode") if context.metadata else None

        # Create session response
        session = SessionResponse(
            id=context.session_id,
            user_id=context.user_id,
            title=f"Session {context.session_id[-8:]}",
            created_at=created_at_ms,
            updated_at=updated_at_ms,
            task_count=len(tasks),  # Use actual task count
            mode=mode,  # Add mode from session metadata
        )

        return SessionDetailsResponse(
            session=session,
            messages=messages,
            tasks=tasks,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error getting session details: {e}")
        raise HTTPException(status_code=500, detail=str(e))
