"""
CopilotChat Repository - CRUD for Copilot conversation history.
"""

import uuid as uuid_lib
from typing import Any, Dict, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import CopilotChat

from .base import BaseRepository


class CopilotChatRepository(BaseRepository[CopilotChat]):
    """CopilotChat data access: query by graph_id + user_id, append messages, delete."""

    def __init__(self, db: AsyncSession):
        super().__init__(CopilotChat, db)

    async def get_chat(self, graph_id: str, user_id: Optional[str]) -> Optional[CopilotChat]:
        """Get CopilotChat by graph_id and user_id."""
        if not user_id:
            return None
        try:
            graph_uuid = uuid_lib.UUID(graph_id)
        except (ValueError, TypeError):
            return None
        return await self.get_by(agent_graph_id=graph_uuid, user_id=user_id)

    async def create_or_append_messages(
        self,
        graph_id: str,
        user_id: Optional[str],
        user_msg_dict: Dict[str, Any],
        assistant_msg_dict: Dict[str, Any],
        title: Optional[str] = None,
    ) -> bool:
        """
        Create a new CopilotChat or append user + assistant messages to existing one.
        Caller must commit the session after this returns True.
        """
        if not user_id:
            logger.warning("[CopilotChatRepository] create_or_append_messages: user_id is required")
            return False
        try:
            graph_uuid = uuid_lib.UUID(graph_id)
        except (ValueError, TypeError):
            logger.warning(f"[CopilotChatRepository] Invalid graph_id: {graph_id}")
            return False

        chat = await self.get_chat(graph_id=graph_id, user_id=user_id)

        if chat:
            existing_messages = list(chat.messages or [])
            existing_messages.append(user_msg_dict)
            existing_messages.append(assistant_msg_dict)
            chat.messages = existing_messages
            from datetime import datetime, timezone

            chat.updated_at = datetime.now(timezone.utc)
            logger.info(f"[CopilotChatRepository] Appended messages to existing chat for graph_id={graph_id}")
        else:
            chat = CopilotChat(
                user_id=user_id,
                agent_graph_id=graph_uuid,
                title=title or (str(user_msg_dict.get("content", ""))[:100] or "Copilot Chat"),
                messages=[user_msg_dict, assistant_msg_dict],
                model="default",
            )
            self.db.add(chat)
            logger.info(f"[CopilotChatRepository] Created new chat for graph_id={graph_id}")

        await self.db.flush()
        return True

    async def delete_by_graph_and_user(self, graph_id: str, user_id: Optional[str]) -> bool:
        """Delete CopilotChat for the given graph_id and user_id. Caller must commit."""
        if not user_id:
            return False
        try:
            graph_uuid = uuid_lib.UUID(graph_id)
        except (ValueError, TypeError):
            return False

        chat = await self.get_by(agent_graph_id=graph_uuid, user_id=user_id)
        if not chat:
            return True

        await self.db.delete(chat)
        await self.db.flush()
        logger.info(f"[CopilotChatRepository] Deleted chat for graph_id={graph_id}")
        return True
