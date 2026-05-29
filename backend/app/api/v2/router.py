from fastapi import APIRouter

from app.api.v2.agents import router as agents_router
from app.api.v2.tasks import router as tasks_router
from app.api.v2.sessions import router as sessions_router
from app.api.v2.environments import router as environments_router
from app.api.v2.secrets import router as secrets_router
from app.api.v2.sandboxes import router as sandboxes_router
from app.api.v2.memory_stores import router as memory_stores_router
from app.api.v2.vaults import router as vaults_router
from app.api.v2.health import router as health_router
from app.api.v2.admin import router as admin_router

conductor_router = APIRouter()

conductor_router.include_router(agents_router, prefix="/agents")
conductor_router.include_router(tasks_router, prefix="/tasks")
conductor_router.include_router(sessions_router, prefix="/sessions")
conductor_router.include_router(environments_router, prefix="/environments")
conductor_router.include_router(secrets_router, prefix="/secrets")
conductor_router.include_router(sandboxes_router, prefix="/sandboxes")
conductor_router.include_router(memory_stores_router, prefix="/memory_stores")
conductor_router.include_router(vaults_router, prefix="/vaults")
conductor_router.include_router(health_router, prefix="/health")
conductor_router.include_router(admin_router, prefix="/admin")
