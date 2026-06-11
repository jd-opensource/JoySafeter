"""API v1 route aggregation.

This module composes all v1 sub-routers into a single `api_router`.
Each sub-router is expected to declare its own `prefix` and `tags`.
"""

from fastapi import APIRouter

from .agent_runs import router as agent_runs_router
from .agents import router as agents_router
from .artifacts import router as artifacts_router
from .auth import router as auth_router
from .copilot import router as copilot_router
from .custom_tools import router as custom_tools_router
from .environment import router as environment_router
from .executions import router as executions_router
from .files import router as files_router
from .mcp import router as mcp_router
from .memory import router as memory_router
from .model_credentials import router as model_credentials_router
from .model_providers import router as model_providers_router
from .model_usage import router as model_usage_router
from .models import router as models_router
from .organizations import router as organizations_router
from .sandboxes import router as sandboxes_router
from .skill_collaborators import router as skill_collaborators_router
from .skill_versions import router as skill_versions_router
from .skills import router as skills_router
from .task_activities import router as task_activities_router
from .tasks import router as tasks_router
from .threads import router as threads_router
from .tokens import router as tokens_router
from .tools import router as tools_router
from .traces import router as traces_router
from .users import router as users_router
from .version import router as version_router

ROUTERS = [
    sandboxes_router,
    auth_router,
    artifacts_router,
    files_router,
    memory_router,
    organizations_router,
    agent_runs_router,
    copilot_router,
    custom_tools_router,
    tools_router,
    mcp_router,
    model_providers_router,
    model_credentials_router,
    models_router,
    model_usage_router,
    skills_router,
    skill_versions_router,
    skill_collaborators_router,
    tokens_router,
    traces_router,
    users_router,
    environment_router,
    version_router,
    tasks_router,
    executions_router,
    agents_router,
    task_activities_router,
    threads_router,
]


api_router = APIRouter()
for router in ROUTERS:
    api_router.include_router(router)

__all__ = ["api_router"]
