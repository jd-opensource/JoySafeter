"""
Module: Sessions API (legacy, based on SessionService)

Overview:
- Provides session CRUD (create, list, get, update title, delete)
- Provides listing messages for a specific session
- Managed via SessionService (legacy module, to be unified with /conversations)

Routes:
- POST /sessions/new_session: Create a session
- GET /sessions: List sessions for the current user
- GET /sessions/{session_id}: Get a specific session
- PATCH /sessions/{session_id}: Update session title
- DELETE /sessions/{session_id}: Delete a session
- GET /sessions/{session_id}/messages: Get messages for a session

Dependencies:
- Session service: SessionService (Depends(get_session_service))
- Database session: Session (Depends(get_db))

Requests/Responses:
- Request model: SessionCreate
- Response models: SessionResponse, MessageResponse
- Unified errors: HTTPException

Notes:
- This implementation does not integrate user authentication yet; get_sessions temporarily returns user_id=1 (TODO: add auth and filter by actual user)
- This module uses legacy relative imports (../models, ../services) and can coexist with newer app.* modules

Error codes:
- 404: Session not found
- 400: Invalid parameters or business rule failure
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.core.database import get_db
from app.schemas.common import SessionCreate, SessionMessageResponse, SessionResponse
from app.services.session_service import SessionService

router = APIRouter()

# ==================== Session endpoints (legacy, based on SessionService) ====================
# ----- Create -----
# ----- Read -----
# ----- Update -----
# ----- Delete -----
# ----- Messages -----


def get_session_service(db: AsyncSession = Depends(get_db)) -> SessionService:
    return SessionService(db)


@router.post("/new_session", response_model=SessionResponse)
async def create_session(
    session_data: SessionCreate,
    current_user: CurrentUser,
    session_service: SessionService = Depends(get_session_service),
):
    """Create a new session."""
    try:
        return await session_service.create_session(session_data, user_id=current_user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[SessionResponse])
async def get_sessions(
    current_user: CurrentUser,
    session_service: SessionService = Depends(get_session_service),
):
    """Get all sessions for the current user."""
    try:
        return await session_service.get_user_sessions(user_id=current_user.id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: str,
    current_user: CurrentUser,
    session_service: SessionService = Depends(get_session_service),
):
    """Get a specific session."""
    session = await session_service.get_session_for_user(session_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session_title(
    session_id: str,
    title: str,
    current_user: CurrentUser,
    session_service: SessionService = Depends(get_session_service),
):
    """Update session title."""
    try:
        updated_session = await session_service.update_session_title(session_id, title, user_id=current_user.id)
        if not updated_session:
            raise HTTPException(status_code=404, detail="Session not found")
        return updated_session
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{session_id}")
async def delete_session(
    session_id: str,
    current_user: CurrentUser,
    session_service: SessionService = Depends(get_session_service),
):
    """Delete a session."""
    try:
        success = await session_service.delete_session(session_id, user_id=current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="Session not found")
        return {"success": True, "message": "Session deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{session_id}/messages", response_model=List[SessionMessageResponse])
async def get_session_messages(
    session_id: str,
    current_user: CurrentUser,
    limit: int = 100,
    session_service: SessionService = Depends(get_session_service),
):
    """Get messages for a session."""
    try:
        messages = await session_service.get_session_messages(session_id, limit, user_id=current_user.id)
        return [
            SessionMessageResponse(
                id=msg.id,
                session_id=msg.thread_id,
                content=msg.content,
                role=msg.role,
                metadata=msg.meta_data,
                created_at=msg.created_at,
            )
            for msg in messages
        ]
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
