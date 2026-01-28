"""
MemoryService

Async operations for Memory table:
- delete_user_memory
- delete_user_memories
- get_all_memory_topics
- get_user_memory
- get_user_memories
- clear_memories

Designed to be SQLite-compatible (uses generic casts/LIKE for search).
"""

import json
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple, Union
from uuid import uuid4

import sqlalchemy as sa
from loguru import logger
from sqlalchemy import String, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, engine
from app.models.memory import Memory
from app.schemas.memory import UserMemory


def log_debug(msg: str) -> None:
    logger.debug(msg)


def log_error(msg: str) -> None:
    logger.error(msg)


def log_warning(msg: str) -> None:
    logger.warning(msg)


def apply_sorting(
    stmt: sa.sql.Select, table: sa.Table, sort_by: Optional[str], sort_order: Optional[str]
) -> sa.sql.Select:
    """
    Apply sorting to a SQLAlchemy select statement based on given sort_by and sort_order.
    - sort_by: column name on the table
    - sort_order: "asc" or "desc"
    Defaults to created_at DESC if not provided or invalid.
    """
    try:
        col = getattr(table.c, sort_by) if sort_by else table.c.created_at
    except AttributeError:
        col = table.c.created_at

    if sort_order and sort_order.lower() == "asc":
        return stmt.order_by(sa.asc(col))
    else:
        return stmt.order_by(sa.desc(col))


class MemoryService:
    """Async service for interacting with memories table."""

    def __init__(self, db: Optional[AsyncSession] = None):
        # 当在 FastAPI 路由里使用时，推荐注入 `AsyncSession`（Depends(get_db)），以统一会话规范；
        # 当在后台任务/脚本中使用时，可不传 db，由服务自行创建短生命周期会话。
        self._db = db

    async def _get_table(self, table_type: str = "memories") -> sa.Table:
        # Currently only supports the 'memories' table
        if table_type != "memories":
            raise ValueError(f"Unsupported table_type: {table_type}")
        table: sa.Table = Memory.__table__  # type: ignore[assignment]
        return table

    def async_session_factory(self) -> AsyncSession:
        # Return an AsyncSession instance for 'async with' usage
        return AsyncSessionLocal()

    @asynccontextmanager
    async def _session(self):
        """获取 AsyncSession，外部注入则复用，否则创建新会话。"""
        if self._db is not None:
            yield self._db
        else:
            async with self.async_session_factory() as sess:
                yield sess

    # -- Memory methods --
    async def delete_user_memory(self, memory_id: str, user_id: str) -> bool:
        """Delete a user memory from the database.

        Args:
            memory_id (str): The ID of the memory to delete.
            user_id (Optional[str]): If provided, only delete the memory when it belongs to this user_id.

        Returns:
            bool: True if deletion was successful, False otherwise.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="memories")

            async with self._session() as sess:
                delete_stmt = table.delete().where(
                    table.c.memory_id == memory_id,
                    table.c.user_id == user_id,
                )
                result = await sess.execute(delete_stmt)
                await sess.commit()

                success = (result.rowcount or 0) > 0  # type: ignore[attr-defined]
                if success:
                    log_debug(f"Successfully deleted user memory id: {memory_id}")
                else:
                    log_debug(f"No user memory found with id: {memory_id}")
                return success

        except Exception as e:
            log_error(f"Error deleting user memory: {e}")
            raise

    async def delete_user_memories(self, memory_ids: List[str], user_id: str) -> None:
        """Delete user memories from the database.

        Args:
            memory_ids (List[str]): The IDs of the memories to delete.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="memories")

            async with self._session() as sess:
                delete_stmt = table.delete().where(
                    table.c.memory_id.in_(memory_ids),
                    table.c.user_id == user_id,
                )
                result = await sess.execute(delete_stmt)
                await sess.commit()

                deleted = result.rowcount or 0  # type: ignore[attr-defined]
                if deleted == 0:
                    log_debug(f"No user memories found with ids: {memory_ids}")
                else:
                    log_debug(f"Successfully deleted {deleted} user memories")

        except Exception as e:
            log_error(f"Error deleting user memories: {e}")
            raise

    async def get_all_memory_topics(self, user_id: str) -> List[str]:
        """Get all memory topics from the database.

        Args:
            user_id: User ID to filter topics by. Only returns topics
                     from memories belonging to this user.

        Returns:
            List[str]: List of unique memory topics.
        """
        try:
            table = await self._get_table(table_type="memories")

            # SQLite-compatible approach: fetch topics column and flatten in Python
            async with self._session() as sess:
                stmt = select(table.c.topics).where(table.c.topics.is_not(None))

                # Always filter by user_id for security (prevent data leakage)
                stmt = stmt.where(table.c.user_id == user_id)

                result = await sess.execute(stmt)
                records = result.fetchall()

            topics_set: set[str] = set()
            for rec in records:
                topics_val = rec[0]
                if isinstance(topics_val, list):
                    for t in topics_val:
                        if isinstance(t, str):
                            topics_set.add(t)

            return list(sorted(topics_set))

        except Exception as e:
            log_error(f"Exception reading topics from memory table: {e}")
            return []

    async def get_user_memory(
        self, memory_id: str, user_id: str, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Get a memory from the database.

        Args:
            memory_id (str): The ID of the memory to get.
            deserialize (Optional[bool]): Whether to serialize the memory. Defaults to True.

        Returns:
            Union[UserMemory, Dict[str, Any], None]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

        Raises:
            Exception: If an error occurs during retrieval.
        """
        try:
            table = await self._get_table(table_type="memories")

            async with self._session() as sess:
                stmt = select(table).where(
                    table.c.memory_id == memory_id,
                    table.c.user_id == user_id,
                )
                result = await sess.execute(stmt)
                row = result.fetchone()
                if not row:
                    return None

                memory_raw: Dict[str, Any] = dict(row._mapping)
                if not deserialize:
                    return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
            return None

    async def get_user_memories(
        self,
        *,
        user_id: str,
        agent_id: Optional[str] = None,
        team_id: Optional[str] = None,
        topics: Optional[List[str]] = None,
        search_content: Optional[str] = None,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        sort_by: Optional[str] = None,
        sort_order: Optional[str] = None,
        deserialize: Optional[bool] = True,
    ) -> Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
        """Get memories from the database.

        Args:
            user_id (Optional[str]): The ID of the user to filter by.
            agent_id (Optional[str]): The ID of the agent to filter by.
            team_id (Optional[str]): The ID of the team to filter by.
            topics (Optional[List[str]]): The topics to filter by.
            search_content (Optional[str]): The content to search for.
            limit (Optional[int]): The maximum number of memories to return.
            page (Optional[int]): The page number (1-based).
            sort_by (Optional[str]): The column to sort by.
            sort_order (Optional[str]): The order to sort by ("asc"/"desc").
            deserialize (Optional[bool]): Whether to serialize the memories. Defaults to True.

        Returns:
            Union[List[UserMemory], Tuple[List[Dict[str, Any]], int]]:
                - When deserialize=True: List of UserMemory objects
                - When deserialize=False: Tuple of (memory dictionaries, total count)
        """
        try:
            table = await self._get_table(table_type="memories")

            async with self._session() as sess:
                stmt = select(table)

                # Filtering
                stmt = stmt.where(table.c.user_id == user_id)
                if agent_id is not None:
                    stmt = stmt.where(table.c.agent_id == agent_id)
                if team_id is not None:
                    stmt = stmt.where(table.c.team_id == team_id)
                if topics is not None:
                    # Use database-specific JSON query for better performance and accuracy
                    dialect = engine.dialect.name
                    if dialect == "postgresql":
                        # PostgreSQL: Use JSONB @> operator to check if array contains the topic
                        # Cast JSON to JSONB for proper containment check
                        for topic in topics:
                            # Check if topics JSON array contains the topic string
                            # Using JSONB @> operator: topics::jsonb @> '["topic"]'::jsonb
                            # Escape single quotes in JSON string for SQL safety
                            topic_array_json = json.dumps([topic])
                            # Replace single quotes with escaped single quotes for SQL
                            topic_array_json_escaped = topic_array_json.replace("'", "''")
                            # Use text() with string formatting (safe for JSON strings from json.dumps)
                            stmt = stmt.where(text(f"topics::jsonb @> '{topic_array_json_escaped}'::jsonb"))
                    else:
                        # SQLite or other: Use LIKE for compatibility
                        for topic in topics:
                            # Match JSON array string content in a dialect-agnostic way
                            stmt = stmt.where(cast(table.c.topics, String).like(f'%"{topic}"%'))
                if search_content is not None:
                    # Search within JSON text by casting to String and using LIKE
                    stmt = stmt.where(cast(table.c.memory, String).like(f"%{search_content}%"))

                # Get total count after applying filtering
                count_stmt = select(func.count()).select_from(stmt.alias())
                total_count = await sess.scalar(count_stmt) or 0

                # Sorting
                stmt = apply_sorting(stmt, table, sort_by, sort_order)

                # Paginating
                if limit is not None:
                    stmt = stmt.limit(limit)
                    if page is not None and page > 0:
                        stmt = stmt.offset((page - 1) * limit)

                result = await sess.execute(stmt)
                records = result.fetchall()
                if not records:
                    return [] if deserialize else ([], 0)

                memories_raw: List[Dict[str, Any]] = [dict(record._mapping) for record in records]
                if not deserialize:
                    return memories_raw, total_count

            return [UserMemory.from_dict(record) for record in memories_raw]

        except Exception as e:
            log_error(f"Exception reading from memory table: {e}")
            return [] if deserialize else ([], 0)

    async def upsert_user_memory(
        self, memory: UserMemory, deserialize: Optional[bool] = True
    ) -> Optional[Union[UserMemory, Dict[str, Any]]]:
        """Upsert a user memory in the database.

        Args:
            memory (UserMemory): The user memory to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memory. Defaults to True.

        Returns:
            Optional[Union[UserMemory, Dict[str, Any]]]:
                - When deserialize=True: UserMemory object
                - When deserialize=False: UserMemory dictionary

        Raises:
            Exception: If an error occurs during upsert.
        """
        try:
            table = await self._get_table(table_type="memories")

            async with self._session() as sess:
                if memory.memory_id is None:
                    memory.memory_id = str(uuid4())

                current_time = int(time.time())

                values = {
                    "memory_id": memory.memory_id,
                    "memory": memory.memory,
                    "input": memory.input,
                    "user_id": memory.user_id,
                    "agent_id": memory.agent_id,
                    "team_id": memory.team_id,
                    "topics": memory.topics,
                    "feedback": memory.feedback,
                    "created_at": memory.created_at,
                    "updated_at": memory.created_at,
                }

                row = None
                dialect = engine.dialect.name

                if dialect == "postgresql":
                    stmt: Any = pg_insert(table).values(**values)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["memory_id"],
                        set_=dict(
                            memory=memory.memory,
                            topics=memory.topics,
                            input=memory.input,
                            agent_id=memory.agent_id,
                            team_id=memory.team_id,
                            feedback=memory.feedback,
                            updated_at=current_time,
                            # Preserve created_at on update - don't overwrite existing value
                            created_at=table.c.created_at,
                        ),
                    ).returning(table)
                    result = await sess.execute(stmt)
                    row = result.fetchone()

                elif dialect == "sqlite":
                    stmt = sqlite_insert(table).values(**values)  # type: ignore[assignment]
                    stmt = stmt.on_conflict_do_update(  # type: ignore[assignment]
                        index_elements=["memory_id"],
                        set_=dict(
                            memory=memory.memory,
                            topics=memory.topics,
                            input=memory.input,
                            agent_id=memory.agent_id,
                            team_id=memory.team_id,
                            feedback=memory.feedback,
                            updated_at=current_time,
                            # Preserve created_at on update - don't overwrite existing value
                            created_at=table.c.created_at,
                        ),
                    ).returning(table)
                    result = await sess.execute(stmt)
                    row = result.fetchone()

                else:
                    # Fallback implementation for other dialects:
                    # Try INSERT, on IntegrityError perform UPDATE
                    try:
                        await sess.execute(sa.insert(table).values(**values))
                    except IntegrityError:
                        await sess.execute(
                            table.update()
                            .where(table.c.memory_id == memory.memory_id)
                            .values(
                                memory=memory.memory,
                                topics=memory.topics,
                                input=memory.input,
                                agent_id=memory.agent_id,
                                team_id=memory.team_id,
                                feedback=memory.feedback,
                                updated_at=current_time,
                            )
                        )
                    result = await sess.execute(select(table).where(table.c.memory_id == memory.memory_id))
                    row = result.fetchone()

                await sess.commit()

            if not row:
                return None

            memory_raw: Dict[str, Any] = dict(row._mapping)
            if not memory_raw or not deserialize:
                return memory_raw

            return UserMemory.from_dict(memory_raw)

        except Exception as e:
            log_error(f"Exception upserting user memory: {e}")
            raise

    async def upsert_memories(
        self, memories: List[UserMemory], deserialize: Optional[bool] = True, preserve_updated_at: bool = False
    ) -> List[Union[UserMemory, Dict[str, Any]]]:
        """
        Bulk insert or update multiple memories in the database for improved performance.

        Args:
            memories (List[UserMemory]): The list of memories to upsert.
            deserialize (Optional[bool]): Whether to deserialize the memories. Defaults to True.
            preserve_updated_at (bool): If True, preserve the updated_at from the memory object.
                                        If False (default), set updated_at to current time.

        Returns:
            List[Union[UserMemory, Dict[str, Any]]]: List of upserted memories

        Raises:
            Exception: If an error occurs during bulk upsert.
        """
        try:
            if not memories:
                return []

            table = await self._get_table(table_type="memories")

            # Prepare memory records for bulk insert
            memory_records: List[Dict[str, Any]] = []
            current_time = int(time.time())

            for m in memories:
                if m.memory_id is None:
                    m.memory_id = str(uuid4())

                # Use preserved updated_at if flag is set (even if None), otherwise use current time
                updated_at = m.updated_at if preserve_updated_at else current_time

                memory_records.append(
                    {
                        "memory_id": m.memory_id,
                        "memory": m.memory,
                        "input": m.input,
                        "user_id": m.user_id,
                        "agent_id": m.agent_id,
                        "team_id": m.team_id,
                        "topics": m.topics,
                        "feedback": m.feedback,
                        "created_at": m.created_at,
                        "updated_at": updated_at,
                    }
                )

            results: List[Union[UserMemory, Dict[str, Any]]] = []

            async with self._session() as sess:
                dialect = engine.dialect.name

                if dialect in ("postgresql", "sqlite"):
                    insert_stmt = pg_insert(table) if dialect == "postgresql" else sqlite_insert(table)
                    update_columns = {
                        col.name: insert_stmt.excluded[col.name]  # type: ignore[attr-defined]
                        for col in table.columns
                        if col.name not in ["memory_id", "created_at"]  # Don't update primary key or created_at
                    }
                    stmt = insert_stmt.on_conflict_do_update(
                        index_elements=["memory_id"], set_=update_columns
                    ).returning(table)

                    result = await sess.execute(stmt, memory_records)
                    rows = result.fetchall()

                else:
                    # Fallback for other dialects: iterate and upsert individually
                    for rec in memory_records:
                        try:
                            await sess.execute(sa.insert(table).values(**rec))
                        except IntegrityError:
                            await sess.execute(
                                table.update()
                                .where(table.c.memory_id == rec["memory_id"])
                                .values({k: v for k, v in rec.items() if k not in ["memory_id", "created_at"]})
                            )
                    # Fetch the upserted rows
                    ids = [rec["memory_id"] for rec in memory_records]
                    result = await sess.execute(select(table).where(table.c.memory_id.in_(ids)))
                    rows = result.fetchall()

                await sess.commit()

                for row in rows:
                    memory_dict = dict(row._mapping)
                    if deserialize:
                        deserialized_memory = UserMemory.from_dict(memory_dict)
                        if deserialized_memory is None:
                            continue
                        results.append(deserialized_memory)
                    else:
                        results.append(memory_dict)

            return results

        except Exception as e:
            log_error(f"Exception bulk upserting memories: {e}")
            return []

    async def clear_memories(self) -> None:
        """Delete all memories from the database.

        Raises:
            Exception: If an error occurs during deletion.
        """
        try:
            table = await self._get_table(table_type="memories")

            async with self._session() as sess:
                await sess.execute(table.delete())
                await sess.commit()

        except Exception as e:
            log_warning(f"Exception deleting all memories: {e}")
            raise
