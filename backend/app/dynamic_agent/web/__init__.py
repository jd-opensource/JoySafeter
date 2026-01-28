"""
Web API Module.

Exports the main API router which aggregates all sub-routers.
"""

from fastapi import APIRouter

from app.dynamic_agent.web.routes.history import router as history_router
from app.dynamic_agent.web.routes.scan import router as scan_router
from app.dynamic_agent.web.routes.sessions import router as sessions_router
from app.dynamic_agent.web.routes.tasks import router as tasks_router
from app.dynamic_agent.web.routes.tools import router as tools_router

# Re-export models for compatibility
from .models import (
    AgentResponse,
    ChatMessageResponse,
    ErrorResponse,
    ExecutionTreeResponse,
    SessionDetailsResponse,
    SessionListResponse,
    SessionResponse,
    TaskBasicResponse,
    TaskListResponse,
    TaskSummaryResponse,
    ToolInfo,
    ToolInvocationResponse,
)

# Main API Router
# All routes will be prefixed with /api
router = APIRouter(prefix="/api")

# 1. Web Visualization Routes (Mocked for now, migrating to real)
# Prefix: /api/web
web_router = APIRouter(prefix="/web")
web_router.include_router(sessions_router)  # /api/web/users/{uid}/sessions
web_router.include_router(tools_router)  # /api/web/tools
web_router.include_router(history_router)

router.include_router(web_router)

# 2. Core Task Routes (Real implementation)
# Prefix: /api/tasks
router.include_router(tasks_router)

# 3. Whitebox Scan Routes
# Prefix: /api/scan
router.include_router(scan_router)

__all__ = [
    "router",
    "SessionResponse",
    "SessionDetailsResponse",
    "SessionListResponse",
    "TaskBasicResponse",
    "TaskSummaryResponse",
    "TaskListResponse",
    "ExecutionTreeResponse",
    "AgentResponse",
    "ToolInvocationResponse",
    "ChatMessageResponse",
    "ToolInfo",
    "ErrorResponse",
]
