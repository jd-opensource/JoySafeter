"""
Task DAO Module.

Handles Task and ExecutionStep database operations using raw SQL and asyncpg.
Replaces the previous SQLAlchemy-based TaskRepository and ExecutionStepRepository.
"""

import asyncio
import json
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Dict, List, Optional, TypeVar
from uuid import UUID

import asyncpg
from loguru import logger

from app.dynamic_agent.storage.models import ExecutionStepResponse, ExecutionStepStatus, TaskResponse, TaskStatus

T = TypeVar("T")


class TaskDAO:
    """Data Access Object for Tasks and Execution Steps."""

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool
        # No global lock - asyncpg pool handles concurrency internally

    def _get_pool_stats(self) -> dict:
        """Get connection pool statistics for debugging.

        Returns:
            Dictionary with pool metrics: size, max_size, min_size, available, in_use
        """
        try:
            pool = self.pool
            if pool is None:
                return {"error": "Pool is None", "pool_object": str(self.pool)}

            # Use asyncpg 0.31.0+ public API
            stats = {
                "pool_type": str(type(pool).__name__),
            }

            # Try new API methods (asyncpg 0.31.0+)
            try:
                size_val = pool.get_size() if hasattr(pool, "get_size") else "N/A"
                stats["size"] = str(size_val) if size_val != "N/A" else "N/A"
                max_size_val: int | str = (
                    pool.get_max_size() if hasattr(pool, "get_max_size") else getattr(pool, "_maxsize", "N/A")  # type: ignore[arg-type]
                )
                stats["max_size"] = str(max_size_val) if max_size_val != "N/A" else "N/A"
                min_size_val: int | str = (
                    pool.get_min_size() if hasattr(pool, "get_min_size") else getattr(pool, "_minsize", "N/A")  # type: ignore[arg-type]
                )
                stats["min_size"] = str(min_size_val) if min_size_val != "N/A" else "N/A"
                idle_val = pool.get_idle_size() if hasattr(pool, "get_idle_size") else "N/A"
                stats["idle"] = str(idle_val) if idle_val != "N/A" else "N/A"

                # Calculate in_use
                if isinstance(stats["size"], int) and isinstance(stats["idle"], int):
                    stats["in_use"] = stats["size"] - stats["idle"]
                else:
                    stats["in_use"] = "N/A"

            except Exception as e:
                # Fallback to old private attributes
                size_val = getattr(pool, "_size", "N/A")
                stats["size"] = str(size_val) if size_val != "N/A" else "N/A"
                max_size_val = getattr(pool, "_maxsize", "N/A")
                stats["max_size"] = str(max_size_val) if max_size_val != "N/A" else "N/A"
                min_size_val = getattr(pool, "_minsize", "N/A")
                stats["min_size"] = str(min_size_val) if min_size_val != "N/A" else "N/A"
                stats["_error"] = str(e)

            return stats
        except Exception as e:
            return {"error": f"Failed to get pool stats: {e}", "pool_type": str(type(self.pool))}

    async def _execute_with_retry(
        self, operation: Callable[..., Awaitable[T]], *args, max_retries: int = 3, **kwargs
    ) -> T:
        """Execute database operation with retry logic for connection errors.

        Args:
            operation: Database operation to execute (must be async)
            max_retries: Maximum number of retry attempts

        Returns:
            Result of the operation

        Raises:
            Exception: If all retries fail
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                result = await operation(*args, **kwargs)
                return result

            except asyncio.CancelledError:
                # 🚨 Must re-raise immediately, never swallow
                logger.debug("Operation cancelled, aborting retries")
                raise

            # Catch "another operation is in progress" error specifically
            except asyncpg.exceptions.InterfaceError as e:
                if "another operation is in progress" in str(e):
                    last_error = e

                    if attempt >= max_retries - 1:
                        pool_stats = self._get_pool_stats()
                        logger.error(
                            f"DB connection state error after {max_retries} attempts | Pool Stats: {pool_stats}",
                            exc_info=e,
                        )
                        break

                    # Exponential backoff + jitter
                    wait_time = min(2**attempt * 0.5 + random.uniform(0.1, 0.5), 5.0)

                    pool_stats = self._get_pool_stats()
                    logger.warning(
                        f"DB connection state error (attempt {attempt + 1}/{max_retries}): {e} | "
                        f"Pool Stats: {pool_stats} | "
                        f"Retrying in {wait_time:.2f}s..."
                    )

                    await asyncio.sleep(wait_time)
                else:
                    # Other InterfaceErrors, re-raise directly
                    raise

            except (
                asyncpg.ConnectionDoesNotExistError,
                asyncpg.exceptions.TooManyConnectionsError,
                asyncpg.PostgresConnectionError,
                asyncpg.CannotConnectNowError,
                asyncio.TimeoutError,
                ConnectionResetError,
            ) as e:
                last_error = e

                if attempt >= max_retries - 1:
                    pool_stats = self._get_pool_stats()
                    logger.error(
                        f"DB connection error after {max_retries} attempts | Pool Stats: {pool_stats}", exc_info=e
                    )
                    break

                # Exponential backoff + jitter
                wait_time = min(2**attempt * 0.5 + random.uniform(0.1, 0.5), 5.0)

                pool_stats = self._get_pool_stats()
                logger.warning(
                    f"DB connection error (attempt {attempt + 1}/{max_retries}): {e} | "
                    f"Pool Stats: {pool_stats} | "
                    f"Retrying in {wait_time:.2f}s..."
                )

                await asyncio.sleep(wait_time)

            except Exception:
                # Non-connection errors: re-raise directly
                raise

        assert last_error is not None
        raise last_error

    # --- Task Operations ---

    async def create_task(
        self,
        session_id: str,
        user_input: str,
        message_id: Optional[int] = None,
        metadata: Optional[dict] = None,
        parent_id: Optional[UUID] = None,
        created_by_step_id: Optional[UUID] = None,
    ) -> TaskResponse:
        """Create a new task (or subtask if parent_id is provided)."""
        # Filter out non-serializable objects from metadata
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

        async def _do_create():
            async with self.pool.acquire(timeout=10.0) as conn:
                # Calculate level: if parent_id exists, get parent's level and add 1
                level = 1
                if parent_id:
                    parent_row = await conn.fetchrow("SELECT level FROM tasks WHERE id = $1", parent_id)
                    if parent_row:
                        level = parent_row["level"] + 1
                        logger.info(
                            f"Creating child task with parent_id={parent_id}, parent_level={parent_row['level']}, new_level={level}"
                        )
                    else:
                        logger.warning(f"Parent task {parent_id} not found, using level 1")
                else:
                    logger.info(f"Creating root task with level={level}, user_input='{user_input[:50]}...'")

                row = await conn.fetchrow(
                    """
                    INSERT INTO tasks (session_id, user_input, message_id, status, metadata, parent_id, level, created_by_step_id)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING *
                """,
                    session_id,
                    user_input,
                    message_id,
                    TaskStatus.PENDING.value,
                    json.dumps(serializable_metadata),
                    parent_id,
                    level,
                    created_by_step_id,
                )

                return self._map_task(row)

        return await self._execute_with_retry(_do_create)

    async def get_task_by_id(self, task_id: UUID) -> Optional[TaskResponse]:
        """Get a task by ID."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
                return self._map_task(row) if row else None

        return await self._execute_with_retry(_do_get)

    async def update_task(
        self,
        task_id: UUID,
        status: Optional[TaskStatus] = None,
        result_summary: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Optional[TaskResponse]:
        """Update a task."""

        async def _do_update():
            async with self.pool.acquire(timeout=5.0) as conn:
                fields = ["updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'"]
                values = []
                idx = 1

                if status:
                    fields.append(f"status = ${idx}")
                    values.append(status.value)
                    idx += 1
                if result_summary is not None:
                    fields.append(f"result_summary = ${idx}")
                    values.append(result_summary)
                    idx += 1
                if completed_at:
                    fields.append(f"completed_at = ${idx}")
                    values.append(completed_at)
                    idx += 1

                values.append(task_id)

                query = f"""
                    UPDATE tasks
                    SET {", ".join(fields)}
                    WHERE id = ${idx}
                    RETURNING *
                """

                row = await conn.fetchrow(query, *values)
                return self._map_task(row) if row else None

        return await self._execute_with_retry(_do_update)

    async def update_task_metadata(self, task_id: UUID, metadata_updates: dict) -> Optional[TaskResponse]:
        """Update task metadata by merging with existing metadata.

        Args:
            task_id: ID of the task to update
            metadata_updates: Dictionary of metadata key-value pairs to add/update

        Returns:
            Updated task response or None if task not found
        """

        async def _do_update():
            async with self.pool.acquire(timeout=5.0) as conn:
                # Get current task
                row = await conn.fetchrow("SELECT * FROM tasks WHERE id = $1", task_id)
                if not row:
                    return None

                # Merge existing metadata with updates
                existing_metadata = {}
                if row["metadata"]:
                    try:
                        existing_metadata = json.loads(row["metadata"])
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Failed to parse existing metadata for task {task_id}")

                # Merge metadata (updates take precedence)
                merged_metadata = {**existing_metadata, **metadata_updates}

                # Filter out non-serializable objects
                serializable_metadata = {}
                for k, v in merged_metadata.items():
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

                # Update the task
                updated_row = await conn.fetchrow(
                    """
                    UPDATE tasks
                    SET metadata = $1, updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                    WHERE id = $2
                    RETURNING *
                """,
                    json.dumps(serializable_metadata),
                    task_id,
                )

                return self._map_task(updated_row) if updated_row else None

        return await self._execute_with_retry(_do_update)

    async def get_tasks_by_session(
        self, session_id: str, limit: int = 50, offset: int = 0
    ) -> tuple[List[TaskResponse], int]:
        """Get root tasks for a session with pagination."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                total = await conn.fetchval(
                    "SELECT COUNT(*) FROM tasks WHERE session_id = $1 AND parent_id IS NULL", session_id
                )

                rows = await conn.fetch(
                    """
                    SELECT * FROM tasks
                    WHERE session_id = $1 AND parent_id IS NULL
                    ORDER BY created_at DESC
                    LIMIT $2 OFFSET $3
                """,
                    session_id,
                    limit,
                    offset,
                )

                return [self._map_task(row) for row in rows], total

        return await self._execute_with_retry(_do_get)

    async def get_subtasks(self, parent_id: UUID) -> List[TaskResponse]:
        """Get all subtasks of a parent task."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM tasks
                    WHERE parent_id = $1
                    ORDER BY created_at ASC
                """,
                    parent_id,
                )
                return [self._map_task(row) for row in rows]

        return await self._execute_with_retry(_do_get)

    async def get_subtasks_by_step(self, created_by_step_id: UUID) -> List[TaskResponse]:
        """Get all subtasks created by a specific execution step."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM tasks
                    WHERE created_by_step_id = $1
                    ORDER BY created_at ASC
                """,
                    created_by_step_id,
                )
                return [self._map_task(row) for row in rows]

        return await self._execute_with_retry(_do_get)

    async def get_tasks_batch(self, task_ids: List[UUID]) -> Dict[UUID, TaskResponse]:
        """Get multiple tasks by IDs in a single query."""
        if not task_ids:
            return {}

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM tasks
                    WHERE id = ANY($1)
                """,
                    task_ids,
                )
                return {row["id"]: self._map_task(row) for row in rows}

        return await self._execute_with_retry(_do_get)

    async def get_root_tasks(self, session_id: str) -> List[TaskResponse]:
        """Get all root tasks for a session."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM tasks
                    WHERE session_id = $1 AND parent_id IS NULL
                    ORDER BY created_at DESC
                """,
                    session_id,
                )
                return [self._map_task(row) for row in rows]

        return await self._execute_with_retry(_do_get)

    async def get_task_id_by_message_id(self, message_id: int) -> Optional[str]:
        """Get task_id by message_id."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                row = await conn.fetchrow(
                    """
                    SELECT id FROM tasks
                    WHERE message_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """,
                    message_id,
                )
                return str(row["id"]) if row else None

        return await self._execute_with_retry(_do_get)

    # --- Execution Step Operations ---

    async def create_step_with_id(
        self,
        step_id: UUID,
        task_id: UUID,
        step_type: str,
        name: str,
        input_data: Optional[dict] = None,
        agent_trace: Optional[dict] = None,
    ) -> ExecutionStepResponse:
        """Create a new execution step with a pre-generated step_id.

        Args:
            step_id: Pre-generated UUID for this step
            task_id: Task ID this step belongs to
            step_type: Type of step (TOOL, LLM, etc.)
            name: Name of the step
            input_data: Input data for the step
            agent_trace: Optional agent trace data

        Returns:
            Created ExecutionStepResponse
        """

        async def _do_create():
            async with self.pool.acquire(timeout=15.0) as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        INSERT INTO execution_steps (
                            id, task_id, step_type, name, input_data,
                            status, agent_trace
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7)
                        RETURNING *
                    """,
                        step_id,
                        task_id,
                        step_type,
                        name,
                        json.dumps(input_data or {}),
                        ExecutionStepStatus.RUNNING.value,
                        json.dumps(agent_trace) if agent_trace else None,
                    )

                    await conn.execute(
                        "UPDATE tasks SET updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = $1", task_id
                    )

                    return self._map_step(row)

        return await self._execute_with_retry(_do_create)

    async def create_step(
        self,
        task_id: UUID,
        step_type: str,
        name: str,
        input_data: Optional[dict] = None,
        agent_trace: Optional[dict] = None,
    ) -> ExecutionStepResponse:
        """Create a new execution step."""

        async def _do_create():
            # Timeout for acquiring connection from pool.
            # In high-concurrency scenarios (e.g., 10 sub-agents with frequent LLM/tool callbacks),
            # the pool can be temporarily exhausted. Need enough time for queue waiting.
            # Balance: too short = frequent timeouts, too long = hangs on actual failures.
            async with self.pool.acquire(timeout=15.0) as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        """
                        INSERT INTO execution_steps (
                            task_id, step_type, name, input_data,
                            status, agent_trace
                        )
                        VALUES ($1, $2, $3, $4, $5, $6)
                        RETURNING *
                    """,
                        task_id,
                        step_type,
                        name,
                        json.dumps(input_data or {}),
                        ExecutionStepStatus.RUNNING.value,
                        json.dumps(agent_trace) if agent_trace else None,
                    )

                    await conn.execute(
                        "UPDATE tasks SET updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = $1", task_id
                    )

                    return self._map_step(row)

        return await self._execute_with_retry(_do_create)

    async def get_step_by_id(self, step_id: UUID) -> Optional[ExecutionStepResponse]:
        """Get step by ID."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                row = await conn.fetchrow("SELECT * FROM execution_steps WHERE id = $1", step_id)
                return self._map_step(row) if row else None

        return await self._execute_with_retry(_do_get)

    async def update_step(
        self,
        step_id: UUID,
        status: Optional[ExecutionStepStatus] = None,
        output_data: Optional[dict] = None,
        error_message: Optional[str] = None,
    ) -> Optional[ExecutionStepResponse]:
        """Update execution step."""

        async def _do_update():
            # Timeout for acquiring connection from pool (same as create_step)
            async with self.pool.acquire(timeout=15.0) as conn:
                async with conn.transaction():
                    fields = []
                    values = []
                    idx = 1

                    if status:
                        fields.append(f"status = ${idx}")
                        values.append(status.value)
                        idx += 1

                        if status in (ExecutionStepStatus.COMPLETED, ExecutionStepStatus.FAILED):
                            fields.append("end_time = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'")

                    if output_data is not None:
                        fields.append(f"output_data = ${idx}")
                        values.append(json.dumps(output_data))
                        idx += 1
                    if error_message is not None:
                        fields.append(f"error_message = ${idx}")
                        values.append(error_message)
                        idx += 1

                    if not fields:
                        return await self.get_step_by_id(step_id)

                    values.append(step_id)

                    query = f"""
                        UPDATE execution_steps
                        SET {", ".join(fields)}
                        WHERE id = ${idx}
                        RETURNING *
                    """

                    row = await conn.fetchrow(query, *values)

                    if row:
                        await conn.execute(
                            "UPDATE tasks SET updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC' WHERE id = (SELECT task_id FROM execution_steps WHERE id = $1)",
                            step_id,
                        )

                    return self._map_step(row) if row else None

        return await self._execute_with_retry(_do_update)

    async def get_all_steps_for_task(self, task_id: UUID) -> List[ExecutionStepResponse]:
        """Get all execution steps for a task."""

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM execution_steps
                    WHERE task_id = $1
                    ORDER BY created_at
                """,
                    task_id,
                )
                return [self._map_step(row) for row in rows]

        return await self._execute_with_retry(_do_get)

    async def get_steps_batch(self, task_ids: List[UUID]) -> Dict[UUID, List[ExecutionStepResponse]]:
        """Get execution steps for multiple tasks."""
        if not task_ids:
            return {}

        async def _do_get():
            async with self.pool.acquire(timeout=5.0) as conn:
                rows = await conn.fetch(
                    """
                    SELECT * FROM execution_steps
                    WHERE task_id = ANY($1)
                    ORDER BY task_id, created_at
                """,
                    task_ids,
                )

                result: Dict[UUID, List[ExecutionStepResponse]] = {}
                for row in rows:
                    task_id = row["task_id"]
                    if task_id not in result:
                        result[task_id] = []
                    result[task_id].append(self._map_step(row))

                return result

        return await self._execute_with_retry(_do_get)

    # --- Mappers ---

    def _map_task(self, row: asyncpg.Record) -> TaskResponse:
        """Map DB row to TaskResponse Pydantic model."""
        # Handle session_id: it might be a UUID object, UUID string, or plain string
        session_id_value = row["session_id"]
        if isinstance(session_id_value, str):
            try:
                # Try to parse as UUID
                session_id_value = UUID(session_id_value)
            except ValueError:
                # If not a valid UUID, generate a deterministic UUID from the string
                # Using uuid5 with a namespace ensures the same string always maps to the same UUID
                import uuid

                session_id_value = uuid.uuid5(uuid.NAMESPACE_DNS, session_id_value)
                logger.debug(f"Converted non-UUID session_id '{row['session_id']}' to UUID: {session_id_value}")

        # Convert naive datetime to UTC-aware datetime
        # Database stores UTC time without timezone info
        created_at = row["created_at"]
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        updated_at = row["updated_at"]
        if updated_at and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)

        completed_at = row["completed_at"]
        if completed_at and completed_at.tzinfo is None:
            completed_at = completed_at.replace(tzinfo=timezone.utc)

        return TaskResponse(
            id=row["id"],
            parent_id=row.get("parent_id"),  # Parent task ID for subtasks
            created_by_step_id=row.get("created_by_step_id"),  # Step that created this task
            level=row.get("level", 1),  # Task hierarchy level
            session_id=session_id_value,
            message_id=row.get("message_id"),
            user_input=row["user_input"],
            status=TaskStatus(row["status"]),
            created_at=created_at,
            updated_at=updated_at,
            completed_at=completed_at,
            result_summary=row["result_summary"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def _map_step(self, row: asyncpg.Record) -> ExecutionStepResponse:
        """Map DB row to ExecutionStepResponse Pydantic model."""
        # Convert naive datetime to UTC-aware datetime
        # Database stores UTC time without timezone info
        start_time = row["start_time"]
        if start_time and start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        end_time = row["end_time"]
        if end_time and end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        created_at = row["created_at"]
        if created_at and created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        return ExecutionStepResponse(
            id=row["id"],
            task_id=row["task_id"],
            step_type=row["step_type"],
            name=row["name"],
            input_data=json.loads(row["input_data"]) if row["input_data"] else {},
            output_data=json.loads(row["output_data"]) if row["output_data"] else None,
            status=ExecutionStepStatus(row["status"]),
            start_time=start_time,
            end_time=end_time,
            error_message=row["error_message"],
            agent_trace=json.loads(row["agent_trace"]) if row["agent_trace"] else None,
            created_at=created_at,
        )
