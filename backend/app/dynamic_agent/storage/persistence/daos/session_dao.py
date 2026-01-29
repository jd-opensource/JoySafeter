"""
Session DAO Module.

Handles Session Context operations using raw SQL and asyncpg.
Supports the optimized schema with split messages and metadata tables.
"""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Dict, List, Optional, TypeVar

import asyncpg
from loguru import logger

from app.dynamic_agent.storage.context_manager import SessionContext

T = TypeVar("T")


class SessionDAO:
    """Data Access Object for Session Contexts."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        # No global lock - asyncpg pool handles concurrency internally

    async def _execute_with_retry(
        self, operation: Callable[..., Awaitable[T]], *args, max_retries: int = 3, **kwargs
    ) -> T:
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                result = await operation(*args, **kwargs)
                return result

            except asyncio.CancelledError:
                # 🚨 Must re-raise immediately, never swallow
                logger.debug("Operation cancelled, aborting retries")
                raise

            except (
                asyncpg.ConnectionDoesNotExistError,
                asyncpg.InterfaceError,
                asyncpg.exceptions.TooManyConnectionsError,
                asyncpg.PostgresConnectionError,
                asyncpg.CannotConnectNowError,
                asyncio.TimeoutError,
                ConnectionResetError,
            ) as e:
                last_error = e

                if attempt >= max_retries - 1:
                    logger.error(f"DB connection error after {max_retries} attempts", exc_info=e)
                    break

                # Exponential backoff + jitter
                wait_time = min(2**attempt * 0.1 + random.random() * 0.2, 2.0)

                logger.warning(
                    f"DB connection error (attempt {attempt + 1}/{max_retries}): {e}. Retrying in {wait_time:.2f}s..."
                )

                await asyncio.sleep(wait_time)

            except Exception:
                # Non-connection errors: re-raise directly
                raise

        assert last_error is not None
        raise last_error

    async def add_message(
        self, session_id: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add a single message and return its ID."""
        logger.debug(f"SessionDAO.add_message called for {session_id}")

        serializable_metadata = {}
        if metadata:
            for k, v in metadata.items():
                if k in ["response_queue", "callbacks"]:
                    continue
                if callable(v):
                    continue
                try:
                    json.dumps(v)
                    serializable_metadata[k] = v
                except (TypeError, ValueError):
                    logger.debug(f"Skipping non-serializable metadata key: {k}")
                    continue

        async def _do_insert():
            async with self.pool.acquire(timeout=5.0) as conn:
                result = await conn.fetchval(
                    """
                    INSERT INTO session_messages (session_id, role, content, metadata)
                    VALUES ($1, $2, $3, $4)
                    RETURNING message_id
                """,
                    session_id,
                    role,
                    content,
                    json.dumps(serializable_metadata),
                )
                return result

        return await self._execute_with_retry(_do_insert)

    async def save_context(self, context: SessionContext):
        """Save session context with optimized split tables."""

        async def _do_save():
            async with self.pool.acquire(timeout=30.0) as conn:
                async with conn.transaction():
                    await conn.execute(
                        """
                        INSERT INTO session_contexts (
                            session_id, user_id, created_at, updated_at,
                            container_id, working_directory, scenario
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        ON CONFLICT (session_id) DO UPDATE SET
                            user_id = EXCLUDED.user_id,
                            updated_at = EXCLUDED.updated_at,
                            container_id = EXCLUDED.container_id,
                            working_directory = EXCLUDED.working_directory,
                            scenario = EXCLUDED.scenario
                    """,
                        context.session_id,
                        context.user_id,
                        context.created_at,
                        context.updated_at,
                        context.container_info.container_id if context.container_info else "",
                        context.container_info.working_directory if context.container_info else "",
                        context.scenario,
                    )

                    await conn.execute(
                        """
                        INSERT INTO session_metadata (
                            session_id, metadata, target_info, active_tasks, completed_tasks, updated_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (session_id) DO UPDATE SET
                            metadata = EXCLUDED.metadata,
                            target_info = EXCLUDED.target_info,
                            active_tasks = EXCLUDED.active_tasks,
                            completed_tasks = EXCLUDED.completed_tasks,
                            updated_at = EXCLUDED.updated_at
                    """,
                        context.session_id,
                        json.dumps(context.metadata, default=str),
                        json.dumps(context.target_info, default=str),
                        json.dumps(context.active_tasks, default=str),
                        json.dumps(context.completed_tasks, default=str),
                        context.updated_at,
                    )

                    new_messages = [m for m in context.messages if not m.get("message_id")]

                    if new_messages:
                        # Execute SQL directly, avoiding "another operation is in progress" errors
                        # that can occur when using prepared statements within transactions
                        for msg in new_messages:
                            ts = msg.get("timestamp")
                            if not ts:
                                ts = datetime.utcnow()
                            elif isinstance(ts, str):
                                try:
                                    ts = datetime.fromisoformat(ts)
                                except ValueError:
                                    ts = datetime.utcnow()

                            message_id = await conn.fetchval(
                                """INSERT INTO session_messages (session_id, role, content, timestamp, metadata)
                                   VALUES ($1, $2, $3, $4, $5)
                                   RETURNING message_id""",
                                context.session_id,
                                msg.get("role", "unknown"),
                                msg.get("content", ""),
                                ts,
                                json.dumps(msg.get("metadata", {})),
                            )

                            msg["message_id"] = message_id

        return await self._execute_with_retry(_do_save)

    async def load_context(self, session_id: str) -> Optional[SessionContext]:
        """Load session context from split tables."""

        async def _do_load():
            async with self.pool.acquire(timeout=5.0) as conn:
                row = await conn.fetchrow("SELECT * FROM session_contexts WHERE session_id = $1", session_id)

                if not row:
                    return None

                meta_row = await conn.fetchrow("SELECT * FROM session_metadata WHERE session_id = $1", session_id)

                msg_rows = await conn.fetch(
                    """
                    SELECT message_id, role, content, timestamp, metadata
                    FROM session_messages
                    WHERE session_id = $1
                    ORDER BY timestamp ASC, message_id ASC
                """,
                    session_id,
                )

                messages = []
                for msg in msg_rows:
                    m_dict = {
                        "message_id": msg["message_id"],
                        "role": msg["role"],
                        "content": msg["content"],
                        "timestamp": msg["timestamp"].isoformat() if msg["timestamp"] else None,
                    }
                    if msg["metadata"]:
                        m_dict["metadata"] = json.loads(msg["metadata"])
                    messages.append(m_dict)

                active_tasks = json.loads(meta_row["active_tasks"]) if meta_row and meta_row["active_tasks"] else {}
                completed_tasks = (
                    json.loads(meta_row["completed_tasks"]) if meta_row and meta_row["completed_tasks"] else []
                )
                metadata = json.loads(meta_row["metadata"]) if meta_row and meta_row["metadata"] else {}
                target_info = json.loads(meta_row["target_info"]) if meta_row and meta_row["target_info"] else {}

                return SessionContext(
                    session_id=row["session_id"],
                    user_id=row["user_id"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    messages=messages,
                    active_tasks=active_tasks,
                    completed_tasks=completed_tasks,
                    metadata=metadata,
                    scenario=row["scenario"],
                    target_info=target_info,
                )

        return await self._execute_with_retry(_do_load)

    async def list_user_sessions(
        self, user_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[List[Dict[str, Any]], int]:
        """List all sessions for a user with pagination."""

        async def _do_list():
            async with self.pool.acquire(timeout=5.0) as conn:
                total = await conn.fetchval("SELECT COUNT(*) FROM session_contexts WHERE user_id = $1", user_id)

                rows = await conn.fetch(
                    """
                    SELECT
                        sc.session_id,
                        sc.user_id,
                        sc.created_at,
                        sc.updated_at,
                        sc.scenario,
                        sm_meta.metadata,
                        COUNT(sm.message_id) as message_count
                    FROM session_contexts sc
                    LEFT JOIN session_messages sm ON sc.session_id = sm.session_id
                    LEFT JOIN session_metadata sm_meta ON sc.session_id = sm_meta.session_id
                    WHERE sc.user_id = $1
                    GROUP BY sc.session_id, sc.user_id, sc.created_at, sc.updated_at, sc.scenario, sm_meta.metadata
                    ORDER BY sc.updated_at DESC
                    LIMIT $2 OFFSET $3
                """,
                    user_id,
                    limit,
                    offset,
                )

                sessions = []
                for row in rows:
                    mode = None
                    if row["metadata"]:
                        try:
                            metadata_dict = json.loads(row["metadata"])
                            mode = metadata_dict.get("mode")
                        except (json.JSONDecodeError, TypeError):
                            logger.debug(f"Could not parse metadata for session {row['session_id']}")

                    sessions.append(
                        {
                            "session_id": row["session_id"],
                            "user_id": row["user_id"],
                            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
                            "scenario": row["scenario"],
                            "message_count": row["message_count"] or 0,
                            "mode": mode,
                        }
                    )

                return sessions, total

        return await self._execute_with_retry(_do_list)
