"""Session management service."""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ai_adapter import AgentBridge
from app.core.settings import settings
from app.models import Conversation, Message
from app.schemas.common import SessionCreate, SessionResponse
from app.utils.datetime import utc_now


class SessionService:
    """Service for managing user sessions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_conversation(
        self, session_id: str, user_id=None, active_only: bool = True
    ) -> Optional[Conversation]:
        where_clauses = [Conversation.thread_id == session_id]
        if user_id is not None:
            where_clauses.append(Conversation.user_id == user_id)
        if active_only:
            where_clauses.append(Conversation.is_active == 1)
        result = await self.db.execute(select(Conversation).where(*where_clauses))
        return result.scalar_one_or_none()

    async def create_session(self, session_data: SessionCreate, user_id) -> SessionResponse:
        """Create a new session."""
        session_id = str(uuid.uuid4())

        # Create workspace directory
        workspace_root = Path(settings.WORKSPACE_ROOT)
        workspace_path = session_data.workspace_path or str(workspace_root / session_id)
        workspace = Path(workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)

        # Create database record
        conversation = Conversation(
            thread_id=session_id,
            user_id=user_id,
            title=session_data.title or "New Session",
            meta_data={"workspace_path": str(workspace)},
            is_active=1,
        )

        self.db.add(conversation)
        await self.db.commit()
        await self.db.refresh(conversation)

        return await self._to_response(conversation)

    async def get_session(self, session_id: str) -> Optional[SessionResponse]:
        """Get session by ID."""
        conversation = await self._get_conversation(session_id, user_id=None, active_only=True)
        if not conversation:
            return None

        return await self._to_response(conversation)

    async def get_session_for_user(self, session_id: str, user_id) -> Optional[SessionResponse]:
        """Get a session by ID, ensuring it belongs to the given user."""
        conversation = await self._get_conversation(session_id, user_id=user_id, active_only=True)
        if not conversation:
            return None
        return await self._to_response(conversation)

    async def get_user_sessions(self, user_id) -> List[SessionResponse]:
        """Get all sessions for a user."""
        result = await self.db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.is_active == 1)
            .order_by(Conversation.updated_at.desc())
        )
        conversations = result.scalars().all()
        responses: List[SessionResponse] = []
        for conv in conversations:
            responses.append(await self._to_response(conv))
        return responses

    async def update_session_title(self, session_id: str, title: str, user_id=None) -> Optional[SessionResponse]:
        """Update session title."""
        conversation = await self._get_conversation(session_id, user_id=user_id, active_only=False)

        if not conversation:
            return None

        conversation.title = title
        conversation.updated_at = utc_now()
        await self.db.commit()
        await self.db.refresh(conversation)

        return await self._to_response(conversation)

    async def delete_session(self, session_id: str, user_id=None) -> bool:
        """Delete a session."""
        conversation = await self._get_conversation(session_id, user_id=user_id, active_only=False)

        if not conversation:
            return False

        # Mark as inactive (soft delete)
        conversation.is_active = 0
        conversation.updated_at = utc_now()
        await self.db.commit()

        # Optionally clean up files
        try:
            workspace_path = (conversation.meta_data or {}).get("workspace_path")
            if workspace_path:
                workspace = Path(workspace_path)
            else:
                workspace = Path(settings.WORKSPACE_ROOT) / session_id
            if workspace.exists() and workspace.is_dir():
                import shutil

                shutil.rmtree(workspace)
        except Exception:
            pass  # Ignore cleanup errors

        return True

    async def add_message(
        self,
        session_id: str,
        content: str,
        role: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """Add a message to the session."""
        message = Message(
            thread_id=session_id,
            content=content,
            role=role,
            meta_data=metadata or {},
        )

        self.db.add(message)

        # Update session timestamp
        result = await self.db.execute(select(Conversation).where(Conversation.thread_id == session_id))
        conversation = result.scalar_one_or_none()
        if conversation:
            conversation.updated_at = utc_now()

        await self.db.commit()
        await self.db.refresh(message)

        return message

    async def get_session_messages(self, session_id: str, limit: int = 100, user_id=None) -> List[Message]:
        """Get messages for a session."""
        if user_id is not None:
            conv = await self._get_conversation(session_id, user_id=user_id, active_only=False)
            if not conv:
                return []
        result = await self.db.execute(
            select(Message).where(Message.thread_id == session_id).order_by(Message.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def get_ai_adapter(self, session_id: str, user_id=None) -> Optional[AgentBridge]:
        """Get AI adapter for a session (lightweight, no CLI coupling)."""
        conversation = await self._get_conversation(session_id, user_id=user_id, active_only=True)
        if not conversation:
            return None
        workspace_path = (conversation.meta_data or {}).get("workspace_path")
        if not workspace_path:
            workspace_path = str(Path(settings.WORKSPACE_ROOT) / session_id)
        # Construct adapter using the decoupled AgentBridge (engine may be injected elsewhere)
        return AgentBridge(session_id, workspace_path)

    async def _to_response(self, conversation: Conversation) -> SessionResponse:
        """Convert database model to response schema."""
        count_result = await self.db.execute(
            select(func.count(Message.id)).where(Message.thread_id == conversation.thread_id)
        )
        message_count = count_result.scalar() or 0
        workspace_path = (conversation.meta_data or {}).get("workspace_path") or str(
            Path(settings.WORKSPACE_ROOT) / conversation.thread_id
        )

        return SessionResponse(
            success=True,
            code=200,
            msg="Success",
            session_id=conversation.thread_id,
            title=conversation.title,
            workspace_path=workspace_path,
            is_active=conversation.is_active == 1,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=message_count,
        )
