from fastapi import APIRouter

from app.joysafeter_api.api.v2.agents import router as agents_router
from app.joysafeter_api.api.v2.auth import router as auth_router
from app.joysafeter_api.api.v2.tasks import router as tasks_router
from app.joysafeter_api.api.v2.sessions import router as sessions_router
from app.joysafeter_api.api.v2.environments import router as environments_router
from app.joysafeter_api.api.v2.secrets import router as secrets_router
from app.joysafeter_api.api.v2.skills import router as skills_router
from app.joysafeter_api.api.v2.sandboxes import router as sandboxes_router
from app.joysafeter_api.api.v2.memory_stores import router as memory_stores_router
from app.joysafeter_api.api.v2.vaults import router as vaults_router
from app.joysafeter_api.api.v2.files import router as files_router
from app.joysafeter_api.api.v2.health import router as health_router
from app.joysafeter_api.api.v2.organizations import router as organizations_router
from app.joysafeter_api.api.v2.oauth import router as oauth_router
from app.joysafeter_api.api.v2.quickstart import router as quickstart_router

joysafeter_router = APIRouter()

joysafeter_router.include_router(auth_router, prefix="/auth")
joysafeter_router.include_router(oauth_router, prefix="/auth/oauth")
joysafeter_router.include_router(agents_router, prefix="/agents")
joysafeter_router.include_router(tasks_router, prefix="/tasks")
joysafeter_router.include_router(sessions_router, prefix="/sessions")
joysafeter_router.include_router(environments_router, prefix="/environments")
joysafeter_router.include_router(secrets_router, prefix="/secrets")
joysafeter_router.include_router(skills_router, prefix="/skills")
joysafeter_router.include_router(sandboxes_router, prefix="/sandboxes")
joysafeter_router.include_router(memory_stores_router, prefix="/memory_stores")
joysafeter_router.include_router(vaults_router, prefix="/vaults")
joysafeter_router.include_router(files_router, prefix="/files")
joysafeter_router.include_router(health_router, prefix="/health")
joysafeter_router.include_router(organizations_router, prefix="/organizations")
joysafeter_router.include_router(quickstart_router, prefix="/quickstart")
