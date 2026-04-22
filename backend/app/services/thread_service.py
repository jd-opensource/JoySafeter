"""
ThreadService — manages Thread and ThreadMessage lifecycle.
"""

from __future__ import annotations

import uuid
from typing import List

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.exceptions import NotFoundException
from app.models.thread import Thread, ThreadMessage
from app.repositories.thread import ThreadMessageRepository, ThreadRepository
from app.schemas.thread import CreateMessageRequest, CreateThreadRequest, UpdateThreadRequest


class ThreadService:
    """Manages Thread and ThreadMessage entities."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.thread_repo = ThreadRepository(db)
        self.message_repo = ThreadMessageRepository(db)

    # ---- Thread CRUD ----

    async def list_threads(self, agent_id: uuid.UUID) -> List[Thread]:
        return await self.thread_repo.list_by_agent(agent_id)

    async def get_thread(self, thread_id: uuid.UUID) -> Thread:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")
        return thread

    async def get_thread_with_messages(self, thread_id: uuid.UUID) -> Thread:
        thread = await self.thread_repo.get_with_messages(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")
        return thread

    async def create_thread(
        self,
        workspace_id: uuid.UUID,
        user_id: str,
        data: CreateThreadRequest,
    ) -> Thread:
        thread = await self.thread_repo.create(
            {
                "agent_id": data.agent_id,
                "workspace_id": workspace_id,
                "title": data.title,
                "status": "active",
                "created_by": user_id,
            }
        )
        logger.info(f"Created thread {thread.id} for agent {data.agent_id}")
        return thread

    async def update_thread(
        self,
        thread_id: uuid.UUID,
        data: UpdateThreadRequest,
    ) -> Thread:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return thread

        updated = await self.thread_repo.update(thread_id, update_data)
        assert updated is not None
        return updated

    async def archive_thread(self, thread_id: uuid.UUID) -> Thread:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")

        updated = await self.thread_repo.update(thread_id, {"status": "archived"})
        assert updated is not None
        logger.info(f"Archived thread {thread_id}")
        return updated

    # ---- Message CRUD ----

    async def list_messages(self, thread_id: uuid.UUID) -> List[ThreadMessage]:
        # Verify thread exists
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")
        return await self.message_repo.list_by_thread(thread_id)

    async def create_message(
        self,
        thread_id: uuid.UUID,
        data: CreateMessageRequest,
    ) -> ThreadMessage:
        thread = await self.thread_repo.get(thread_id)
        if not thread:
            raise NotFoundException(f"Thread {thread_id} not found")

        message = await self.message_repo.create(
            {
                "thread_id": thread_id,
                "role": data.role,
                "content": data.content,
            }
        )
        logger.info(f"Created message {message.id} in thread {thread_id}")
        return message
