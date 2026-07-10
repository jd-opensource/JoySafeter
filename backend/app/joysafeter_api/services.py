"""API-facing service adapters.

API route modules import service dependencies from this module while the current
implementations are exposed through app.joysafeter_domain.services.
"""

from __future__ import annotations

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

# Canonical enqueue lives in the shared layer so every submitter (this API, the
# session follow-up path, and the scheduler) shares one definition and cannot
# drift from the orchestrator's queue contract. Re-exported here to preserve the
# historical `from app.joysafeter_api.services import enqueue_joysafeter_task`.
from app.joysafeter_shared.orchestrator_bridge.enqueue import enqueue_joysafeter_task

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
