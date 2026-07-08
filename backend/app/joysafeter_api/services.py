"""API-facing service adapters.

API route modules import service dependencies from this module while the current
implementations are exposed through app.joysafeter_domain.services.
"""

from __future__ import annotations

import uuid

from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService, _split_packed_items
from app.joysafeter_domain.services.joysafeter_api_key_service import ApiKeyService
from app.joysafeter_domain.services.joysafeter_auth_service import (
    AuthService,
    AuthSessionService,
    OAuthService,
    run_post_login_init,
)
from app.joysafeter_domain.services.joysafeter_environment_service import (
    EnvironmentService as JoySafeterEnvironmentService,
)
from app.joysafeter_domain.services.joysafeter_file_service import FileService
from app.joysafeter_domain.services.joysafeter_memory_service import (
    MemoryService as JoySafeterMemoryService,
)
from app.joysafeter_domain.services.joysafeter_memory_service import (
    MemoryStoreLimitExceeded,
    PreconditionFailed,
)
from app.joysafeter_domain.services.joysafeter_project_service import ProjectService
from app.joysafeter_domain.services.joysafeter_sandbox_service import SandboxService
from app.joysafeter_domain.services.joysafeter_secret_service import SecretService
from app.joysafeter_domain.services.joysafeter_session_service import JoySafeterSessionLifecycleService, SessionService
from app.joysafeter_domain.services.joysafeter_skill_service import (
    SkillLifecycleService,
    SkillService,
    SkillVersionService,
)
from app.joysafeter_domain.services.joysafeter_task_service import JoySafeterTaskService
from app.joysafeter_domain.services.joysafeter_vault_service import VaultService


async def enqueue_joysafeter_task(task_id: uuid.UUID) -> None:
    """Enqueue a task from either monolith/orchestrator or API-only processes."""
    from app.joysafeter_shared.orchestrator_bridge import get_scheduler

    scheduler = get_scheduler()
    if scheduler:
        await scheduler.push_to_global(task_id)
        return

    from app.joysafeter_shared.cache.redis import RedisClient

    redis = RedisClient.get_client()
    if redis is None:
        raise RuntimeError("Redis unavailable; cannot enqueue task to global queue")
    await redis.rpush("joysafeter:global_queue", str(task_id))


__all__ = [
    "ApiKeyService",
    "AuthService",
    "AuthSessionService",
    "JoySafeterAgentService",
    "JoySafeterEnvironmentService",
    "JoySafeterMemoryService",
    "JoySafeterSessionLifecycleService",
    "JoySafeterTaskService",
    "FileService",
    "MemoryStoreLimitExceeded",
    "OAuthService",
    "PreconditionFailed",
    "ProjectService",
    "SandboxService",
    "SecretService",
    "SessionService",
    "SkillLifecycleService",
    "SkillService",
    "SkillVersionService",
    "VaultService",
    "_split_packed_items",
    "enqueue_joysafeter_task",
    "run_post_login_init",
]
