"""API v1 route aggregation.

This module composes all v1 sub-routers into a single `api_router`.
Each sub-router is expected to declare its own `prefix` and `tags`.
"""

from fastapi import APIRouter

from .api_keys import router as api_keys_router
from .auth import router as auth_router
from .chat import router as chat_router
from .copilot_deepagents import router as copilot_deepagents_router
from .custom_tools import router as custom_tools_router
from .environment import router as environment_router
from .graph_deployments import router as graph_deployments_router
from .graphs import router as graphs_router
from .mcp import router as mcp_router
from .model_credentials import router as model_credentials_router
from .model_providers import router as model_providers_router
from .models import router as models_router
from .organizations import router as organizations_router
from .skills import router as skills_router
from .tools import router as tools_router
from .users import router as users_router
from .workspace_files import router as workspace_files_router
from .workspace_folders import router as workspace_folders_router
from .workspaces import router as workspaces_router

ROUTERS = [
    auth_router,
    organizations_router,
    workspaces_router,
    workspace_folders_router,
    workspace_files_router,
    custom_tools_router,
    api_keys_router,
    tools_router,
    mcp_router,
    model_providers_router,
    model_credentials_router,
    models_router,
    graph_deployments_router,
    skills_router,
    chat_router,
    graphs_router,
    copilot_deepagents_router,
    users_router,
    environment_router,
]


api_router = APIRouter()
for router in ROUTERS:
    api_router.include_router(router)

__all__ = ["api_router"]
