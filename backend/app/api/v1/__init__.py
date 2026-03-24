"""API v1 route aggregation.

This module composes all v1 sub-routers into a single `api_router`.
Each sub-router is expected to declare its own `prefix` and `tags`.
"""

from fastapi import APIRouter

from .artifacts import router as artifacts_router
from .auth import router as auth_router
from .chat import router as chat_router
from .conversations import router as conversations_router
from .custom_tools import router as custom_tools_router
from .environment import router as environment_router
from .files import router as files_router
from .graph_deployments import router as graph_deployments_router
from .graph_schemas import router as graph_schemas_router
from .graph_tests import router as graph_tests_router
from .graphs import router as graphs_router
from .mcp import router as mcp_router
from .memory import router as memory_router
from .model_credentials import router as model_credentials_router
from .model_providers import router as model_providers_router
from .models import router as models_router
from .oauth import router as oauth_router
from .openapi_graph import router as openapi_graph_router
from .openclaw_chat import router as openclaw_chat_router
from .openclaw_devices import router as openclaw_devices_router
from .openclaw_instances import router as openclaw_instances_router
from .openclaw_proxy import router as openclaw_proxy_router
from .organizations import router as organizations_router
from .sandboxes import router as sandboxes_router
from .skill_collaborators import router as skill_collaborators_router
from .skill_versions import router as skill_versions_router
from .skills import router as skills_router
from .tokens import router as tokens_router
from .tools import router as tools_router
from .traces import router as traces_router
from .users import router as users_router
from .workspace_files import router as workspace_files_router
from .workspace_folders import router as workspace_folders_router
from .workspaces import router as workspaces_router

ROUTERS = [
    sandboxes_router,
    auth_router,
    artifacts_router,
    conversations_router,
    files_router,
    memory_router,
    oauth_router,
    organizations_router,
    workspaces_router,
    workspace_folders_router,
    workspace_files_router,
    custom_tools_router,
    tools_router,
    mcp_router,
    model_providers_router,
    model_credentials_router,
    models_router,
    graph_deployments_router,
    graph_schemas_router,
    graph_tests_router,
    skills_router,
    skill_versions_router,
    skill_collaborators_router,
    tokens_router,
    chat_router,
    graphs_router,
    traces_router,
    users_router,
    environment_router,
    openclaw_instances_router,
    openclaw_chat_router,
    openclaw_devices_router,
    openclaw_proxy_router,
    openapi_graph_router,
]


api_router = APIRouter()
for router in ROUTERS:
    api_router.include_router(router)

__all__ = ["api_router"]
