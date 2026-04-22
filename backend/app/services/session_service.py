"""Session management service.

The Conversation table has been dropped. Sessions are now lightweight
wrappers around thread_id + Message rows. Workspace paths are derived
from settings.workspace_root / thread_id.
"""

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.models import Message
from app.schemas.common import SessionCreate, SessionResponse
from app.utils.datetime import utc_now


class SessionService:
    """Service for managing user sessions.

    With the Conversation table removed, a "session" is identified by a
    thread_id that groups Message rows. Session metadata (title, active
    flag) is no longer persisted; we synthesise it from the messages.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(self, session_data: SessionCreate, user_id) -> SessionResponse:
        """Create a new session (generates a thread_id and workspace dir)."""
        session_id = str(uuid.uuid4())

        workspace_root = Path(settings.workspace_root)
        workspace_path = session_data.workspace_path or str(workspace_root / session_id)
        workspace = Path(workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)

        now = utc_now()
        return SessionResponse(
            success=True,
            code=200,
            msg="Success",
            session_id=session_id,
            title=session_data.title or "New Session",
            workspace_path=str(workspace),
            is_active=True,
            created_at=now,
            updated_at=now,
            message_count=0,
        )

    async def get_session(self, session_id: str) -> Optional[SessionResponse]:
        """Get session by ID."""
        return await self._build_response(session_id)

    async def get_session_for_user(self, session_id: str, user_id) -> Optional[SessionResponse]:
        """Get a session by ID. Returns None if no messages exist for this thread."""
        return await self._build_response(session_id)

    async def get_user_sessions(self, user_id) -> List[SessionResponse]:
        """Get all sessions (distinct thread_ids) that have messages."""
        stmt = (
            select(
                Message.thread_id,
                func.count(Message.id).label("cnt"),
                func.min(Message.created_at).label("first_at"),
                func.max(Message.created_at).label("last_at"),
            )
            .group_by(Message.thread_id)
            .order_by(func.max(Message.created_at).desc())
        )
        result = await self.db.execute(stmt)
        rows = result.all()

        responses: List[SessionResponse] = []
        for row in rows:
            thread_id = row.thread_id
            workspace_path = str(Path(settings.workspace_root) / thread_id)
            responses.append(
                SessionResponse(
                    success=True,
                    code=200,
                    msg="Success",
                    session_id=thread_id,
                    title=thread_id[:50],
                    workspace_path=workspace_path,
                    is_active=True,
                    created_at=row.first_at,
                    updated_at=row.last_at,
                    message_count=row.cnt,
                )
            )
        return responses

    async def update_session_title(self, session_id: str, title: str, user_id=None) -> Optional[SessionResponse]:
        """Update session title. Since there is no Conversation row, this is a no-op that returns the session."""
        resp = await self._build_response(session_id)
        if resp is not None:
            resp.title = title
        return resp

    async def delete_session(self, session_id: str, user_id=None) -> bool:
        """Delete a session by removing its workspace directory.

        Messages are retained for audit; the session simply won't appear
        in listings once the workspace is gone.
        """
        try:
            workspace = Path(settings.workspace_root) / session_id
            if workspace.exists() and workspace.is_dir():
                import shutil
                shutil.rmtree(workspace)
        except Exception:
            logger.debug("Workspace directory cleanup failed for session %s", session_id, exc_info=True)
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
        await self.db.commit()
        await self.db.refresh(message)
        return message

    async def get_session_messages(self, session_id: str, limit: int = 100, user_id=None) -> List[Message]:
        """Get messages for a session."""
        result = await self.db.execute(
            select(Message)
            .where(Message.thread_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def _build_response(self, session_id: str) -> Optional[SessionResponse]:
        """Build a SessionResponse from Message rows for the given thread_id."""
        stmt = select(
            func.count(Message.id).label("cnt"),
            func.min(Message.created_at).label("first_at"),
            func.max(Message.created_at).label("last_at"),
        ).where(Message.thread_id == session_id)
        result = await self.db.execute(stmt)
        row = result.one_or_none()
        if row is None or row.cnt == 0:
            return None

        workspace_path = str(Path(settings.workspace_root) / session_id)
        return SessionResponse(
            success=True,
            code=200,
            msg="Success",
            session_id=session_id,
            title=session_id[:50],
            workspace_path=workspace_path,
            is_active=True,
            created_at=row.first_at,
            updated_at=row.last_at,
            message_count=row.cnt,
        )
