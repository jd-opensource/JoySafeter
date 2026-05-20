import asyncio
import logging
import os
import uuid
from typing import Optional

from app.conductor.sandbox.provider import SandboxProvider

logger = logging.getLogger(__name__)


class SandboxResolver:
    """3-stage sandbox resolution: session reuse → pool claim → create new.

    Ported from conductor-sandbox/src/resolver.rs.
    """

    def __init__(
        self,
        default_provider: str = "docker",
        default_image: str = "joysafeter/cli-agent:latest",
        pool_enabled: bool = False,
        workspace_host_root: str = "/tmp/conductor/workspaces",
        provider: Optional[SandboxProvider] = None,
    ):
        self._default_provider = default_provider
        self._default_image = default_image
        self._pool_enabled = pool_enabled
        self._workspace_host_root = workspace_host_root
        self._provider = provider
        self._session_locks: dict[uuid.UUID, asyncio.Lock] = {}
        self._session_locks_guard = asyncio.Lock()

    async def _get_session_lock(self, session_id: uuid.UUID) -> asyncio.Lock:
        async with self._session_locks_guard:
            if session_id not in self._session_locks:
                self._session_locks[session_id] = asyncio.Lock()
            lock = self._session_locks[session_id]
        return lock

    def _cleanup_stale_locks(self) -> None:
        stale = [k for k, v in self._session_locks.items() if not v.locked()]
        for k in stale:
            self._session_locks.pop(k, None)

    async def resolve(
        self,
        session_id: uuid.UUID,
        agent_env: dict[str, str],
        image: Optional[str] = None,
        networking: Optional[dict] = None,
    ) -> dict:
        """Resolve a sandbox for the given session.

        Returns dict with keys: sandbox_id, external_id, status, created (bool).
        All DB operations are performed within this method using fresh sessions.
        """
        lock = await self._get_session_lock(session_id)
        async with lock:
            try:
                return await self._resolve_inner(
                    session_id, agent_env, image, networking
                )
            finally:
                self._cleanup_stale_locks()

    async def _resolve_inner(
        self,
        session_id: uuid.UUID,
        agent_env: dict[str, str],
        image: Optional[str],
        networking: Optional[dict] = None,
    ) -> dict:
        from app.core.database import AsyncSessionLocal
        from app.conductor.services.sandbox_service import SandboxService

        resolved_image = image or self._default_image

        # Stage 1: Reuse existing sandbox for this session
        async with AsyncSessionLocal() as db:
            svc = SandboxService(db)
            existing = await svc.find_by_session(session_id)
            if existing:
                if existing.status in ("running", "idle"):
                    logger.info(
                        "Reusing existing sandbox %s (status=%s) for session %s",
                        existing.id, existing.status, session_id,
                    )
                    return {
                        "sandbox_id": existing.id,
                        "external_id": existing.external_id,
                        "status": existing.status,
                        "created": False,
                    }

        # Stage 1b: Try to restart a stopped sandbox for this session
        async with AsyncSessionLocal() as db:
            svc = SandboxService(db)
            stopped = await self._find_stopped_for_session(svc, session_id)
            if stopped:
                restarted = await self._restart_sandbox(svc, stopped)
                if restarted:
                    return {
                        "sandbox_id": stopped.id,
                        "external_id": stopped.external_id,
                        "status": "running",
                        "created": False,
                    }

        # Stage 2: Claim from pool
        if self._pool_enabled:
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                pooled = await svc.claim_from_pool(session_id)
                if pooled:
                    logger.info(
                        "Claimed sandbox %s from pool for session %s",
                        pooled.id, session_id,
                    )
                    return {
                        "sandbox_id": pooled.id,
                        "external_id": pooled.external_id,
                        "status": "running",
                        "created": False,
                    }

        # Stage 3: Create new sandbox
        workspace_path = os.path.join(self._workspace_host_root, str(session_id))
        async with AsyncSessionLocal() as db:
            svc = SandboxService(db)
            sandbox = await svc.create_sandbox(
                image=resolved_image,
                provider=self._default_provider,
                chat_session_id=session_id,
                workspace_path=workspace_path,
                config={
                    "provisioning": {
                        "stage": "creating",
                        "progress": 0,
                        "message": "Creating sandbox container",
                        "complete": False,
                        "error": False,
                    }
                },
            )

        # Provision the sandbox (create + start container)
        try:
            external_id = await self._provision_sandbox(
                sandbox.id, resolved_image, agent_env, workspace_path,
                networking=networking,
            )
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                await svc.update_status_cas(
                    sandbox.id, "creating", "running", external_id=external_id
                )

            # Register with Envoy for network isolation
            await self._register_with_envoy(sandbox.id, networking)

            logger.info("Provisioned sandbox %s (ext=%s)", sandbox.id, external_id)
            return {
                "sandbox_id": sandbox.id,
                "external_id": external_id,
                "status": "running",
                "created": True,
            }
        except Exception as e:
            logger.error("Failed to provision sandbox %s: %s", sandbox.id, e)
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                await svc.update_status_cas(sandbox.id, "creating", "destroyed")
            raise

    async def _find_stopped_for_session(self, svc, session_id: uuid.UUID):
        from sqlalchemy import and_, select
        from app.conductor.models.sandbox import ConductorSandbox

        result = await svc.db.execute(
            select(ConductorSandbox).where(
                and_(
                    ConductorSandbox.chat_session_id == session_id,
                    ConductorSandbox.status == "stopped",
                    ConductorSandbox.destroyed_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    def _get_provider(self) -> SandboxProvider:
        if self._provider:
            return self._provider
        from app.conductor.sandbox.docker_provider import DockerSandboxProvider
        return DockerSandboxProvider()

    async def _restart_sandbox(self, svc, sandbox) -> bool:
        try:
            provider = self._get_provider()
            await provider.start(sandbox.external_id)
            await svc.update_status_cas(sandbox.id, "stopped", "running")
            logger.info("Restarted stopped sandbox %s", sandbox.id)
            return True
        except Exception as e:
            logger.warning("Failed to restart sandbox %s: %s", sandbox.id, e)
            return False

    async def _provision_sandbox(
        self,
        sandbox_id: uuid.UUID,
        image: str,
        env: dict[str, str],
        workspace_path: str,
        networking: Optional[dict] = None,
        memory_mounts: Optional[list[dict]] = None,
    ) -> str:
        os.makedirs(workspace_path, exist_ok=True)

        provider = self._get_provider()
        name = str(sandbox_id)[:8]
        labels = {
            "conductor.sandbox_id": str(sandbox_id),
            "conductor.managed": "true",
        }

        external_id = await provider.create(
            name=name,
            image=image,
            env=env,
            work_dir=workspace_path,
            labels=labels,
            networking=networking,
            memory_mounts=memory_mounts,
        )
        await provider.start(external_id)
        return external_id

    async def _register_with_envoy(
        self, sandbox_id: uuid.UUID, networking: Optional[dict] = None
    ) -> None:
        from app.conductor.lifespan import get_envoy_manager

        envoy = get_envoy_manager()
        if not envoy:
            return

        try:
            net_config = networking or {"allowed_hosts": [], "type": "unrestricted"}
            await envoy.add_sandbox(sandbox_id, net_config)
        except Exception as e:
            logger.warning("Failed to register sandbox %s with Envoy: %s", sandbox_id, e)
