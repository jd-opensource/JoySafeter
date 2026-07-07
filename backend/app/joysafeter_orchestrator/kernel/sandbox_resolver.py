import asyncio
import hashlib
import logging
import os
import uuid
from typing import Optional

from uuid_utils import uuid7 as _uuid7

from app.joysafeter_orchestrator.sandbox.provider import SandboxProvider
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.config.settings import joysafeter_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Multi-image map: per-engine-kind image resolution
# ---------------------------------------------------------------------------

_IMAGE_CONFIG_MAP: dict[str, str] = {
    "claude": "image_claude",
    "codex": "image_codex",
    "native": "image_native",
}


def image_for_provider(engine_kind: str, fallback: str) -> str:
    """Return the container image for a given engine kind.

    Resolution order:
      1. Engine-specific config (joysafeter_config.image_claude / .image_codex)
      2. The *fallback* value (typically ``joysafeter_config.sandbox_image``)
    """
    attr = _IMAGE_CONFIG_MAP.get(engine_kind)
    if attr:
        val = getattr(joysafeter_config, attr, None)
        if val:
            return str(val)
    return fallback


class SandboxResolver:
    """3-stage sandbox resolution: session reuse -> pool claim -> create new.

    Ported from joysafeter-sandbox/src/resolver.rs.
    """

    @staticmethod
    def _provisioning_config(stage: str, progress: int, message: str) -> dict:
        return {
            "provisioning": {
                "stage": stage,
                "progress": progress,
                "message": message,
                "complete": False,
                "error": False,
            }
        }

    @staticmethod
    def _sandbox_fingerprint(
        image: str,
        networking: Optional[dict],
        engine_kind: Optional[str],
        env: Optional[dict[str, str]] = None,
    ) -> dict:
        env_items = env or {}
        return {
            "image": image,
            "engine_kind": engine_kind,
            "networking": networking or {},
            "env": {str(k): hashlib.sha256(str(v).encode("utf-8")).hexdigest() for k, v in sorted(env_items.items())},
        }

    @staticmethod
    def _fingerprint_matches(sandbox, expected: dict) -> bool:
        config = sandbox.config or {}
        actual = config.get("fingerprint")
        if actual is None:
            # Older records have no fingerprint; only allow reuse when the image still matches.
            return bool(sandbox.image == expected.get("image"))
        return bool(actual == expected)

    @staticmethod
    def _with_fingerprint(config: dict, fingerprint: dict) -> dict:
        merged = dict(config or {})
        merged["fingerprint"] = fingerprint
        return merged

    @staticmethod
    def _env_allows_pool_claim(env: dict[str, str]) -> bool:
        """Return True only when a warm pool sandbox can safely be reused.

        Docker container environment variables are immutable after creation.
        Warm pool sandboxes are created without per-agent secrets, so a task
        requiring runtime credentials must get a freshly created sandbox.
        """
        return not env

    @staticmethod
    def _log_boundary_failure(
        *,
        code: str,
        message: str,
        operation: str,
        error: Exception,
        data: dict[str, object] | None = None,
    ) -> None:
        logger.warning(
            message,
            extra={
                "error": async_boundary_error_payload(
                    code=code,
                    message=message,
                    boundary="sandbox_resolver",
                    operation=operation,
                    data=data,
                    detail=error.__class__.__name__,
                )
            },
            exc_info=True,
        )

    def __init__(
        self,
        default_provider: str = "docker",
        default_image: str = "joysafeter-claudecode:latest",
        pool_enabled: bool = False,
        pool_env: Optional[dict[str, str]] = None,
        workspace_host_root: Optional[str] = None,
        provider: Optional[SandboxProvider] = None,
        grpc_public_url: Optional[str] = None,
    ):
        self._default_provider = default_provider
        self._default_image = default_image
        self._pool_enabled = pool_enabled
        self._pool_env: dict[str, str] = dict(pool_env) if pool_env else {}
        self._workspace_host_root = workspace_host_root
        self._provider = provider
        self._grpc_public_url = (
            grpc_public_url
            or joysafeter_config.grpc_public_url
            or f"http://host.docker.internal:{joysafeter_config.grpc_port}"
        )
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
        engine_kind: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        """Resolve a sandbox for the given session.

        Returns dict with keys: sandbox_id, external_id, status, created (bool).
        All DB operations are performed within this method using fresh sessions.
        """
        lock = await self._get_session_lock(session_id)
        async with lock:
            try:
                from sqlalchemy import text

                from app.joysafeter_shared.database import AsyncSessionLocal

                lock_key = f"sandbox_resolve:{session_id}"
                async with AsyncSessionLocal() as lock_db:
                    await lock_db.execute(
                        text("SELECT pg_advisory_lock(hashtext(:lock_key))"),
                        {"lock_key": lock_key},
                    )
                    try:
                        return await asyncio.wait_for(
                            self._resolve_inner(
                                session_id,
                                agent_env,
                                image,
                                networking,
                                engine_kind=engine_kind,
                                project_id=project_id,
                            ),
                            timeout=120.0,
                        )
                    except asyncio.TimeoutError:
                        raise RuntimeError(
                            f"Sandbox resolution timed out after 120s for session {session_id}"
                        ) from None
                    finally:
                        await lock_db.execute(
                            text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                            {"lock_key": lock_key},
                        )
            finally:
                self._cleanup_stale_locks()

    async def _resolve_inner(
        self,
        session_id: uuid.UUID,
        agent_env: dict[str, str],
        image: Optional[str],
        networking: Optional[dict] = None,
        engine_kind: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_orchestrator.services import SessionService
        from app.joysafeter_shared.database import AsyncSessionLocal

        if project_id is None:
            async with AsyncSessionLocal() as db:
                session = await SessionService(db).get_session(session_id)
                if session:
                    project_id = session.project_id

        # Resolve image: explicit arg > engine-kind map > default
        if image:
            resolved_image = image
        elif engine_kind:
            resolved_image = image_for_provider(engine_kind, self._default_image)
        else:
            resolved_image = self._default_image

        expected_fingerprint = self._sandbox_fingerprint(resolved_image, networking, engine_kind, agent_env)

        # Stage 1: Reuse existing sandbox for this session
        async with AsyncSessionLocal() as db:
            svc = SandboxService(db)
            existing = await svc.find_by_session(session_id)
            if existing:
                if not self._fingerprint_matches(existing, expected_fingerprint):
                    logger.info(
                        "Sandbox %s config differs for session %s, creating a fresh sandbox",
                        existing.id,
                        session_id,
                    )
                    if existing.status in ("idle", "stopped", "error"):
                        try:
                            provider = self._get_provider()
                            await provider.destroy(existing.external_id)
                        except Exception:
                            pass
                        await svc.mark_destroyed(existing.id)
                        try:
                            await self._get_provider().teardown_networking(existing.id)
                        except Exception:
                            pass
                    elif existing.status in ("running", "provisioning", "creating"):
                        raise RuntimeError("Session has an active sandbox with different configuration")
                    existing = None

            if existing:
                if existing.status in ("idle", "running"):
                    logger.info(
                        "Reusing existing sandbox %s (status=%s) for session %s",
                        existing.id,
                        existing.status,
                        session_id,
                    )
                    await svc.touch(existing.id)
                    return {
                        "sandbox_id": existing.id,
                        "external_id": existing.external_id,
                        "status": existing.status,
                        "created": False,
                    }
                elif existing.status in ("provisioning", "creating"):
                    logger.info(
                        "Sandbox %s is still %s for session %s, reusing without touch",
                        existing.id,
                        existing.status,
                        session_id,
                    )
                    return {
                        "sandbox_id": existing.id,
                        "external_id": existing.external_id,
                        "status": existing.status,
                        "created": False,
                    }
                elif existing.status == "error":
                    logger.info(
                        "Sandbox %s in error state for session %s, destroying",
                        existing.id,
                        session_id,
                    )
                    provider = self._get_provider()
                    try:
                        await provider.destroy(existing.external_id)
                    except Exception:
                        pass
                    await svc.mark_destroyed(existing.id)
                    try:
                        await provider.teardown_networking(existing.id)
                    except Exception:
                        pass
                elif existing.status == "stopping":
                    logger.info(
                        "Sandbox %s is being stopped for session %s, creating new",
                        existing.id,
                        session_id,
                    )

        # Stage 1b: Try to restart a stopped sandbox for this session
        async with AsyncSessionLocal() as db:
            svc = SandboxService(db)
            stopped = await self._find_stopped_for_session(svc, session_id)
            if stopped:
                if not self._fingerprint_matches(stopped, expected_fingerprint):
                    await svc.mark_destroyed(stopped.id)
                    stopped = None
                    # I14 fix: Rust skips pool after destroying mismatched stopped sandbox
                    # and goes directly to create_new. Match that behavior.
                    return await self._create_new_sandbox(
                        session_id,
                        expected_fingerprint,
                        agent_env,
                        networking,
                        engine_kind,
                        resolved_image,
                    )
                restarted = await self._restart_sandbox(svc, stopped) if stopped else False
                if restarted:
                    return {
                        "sandbox_id": stopped.id,
                        "external_id": stopped.external_id,
                        "status": "provisioning",
                        "created": False,
                    }

        # Stage 2: Claim from pool + liveness check
        # Skip pool claim if net_type is "limited" (requires dedicated container)
        # or if this session needs a persistent host workspace. Docker cannot add
        # a session-specific bind mount to an already-created pooled container.
        net_type = (networking or {}).get("type", "unrestricted")
        requires_persistent_workspace = self._workspace_host_root is not None
        if (
            self._pool_enabled
            and net_type != "limited"
            and not requires_persistent_workspace
            and self._env_allows_pool_claim(agent_env)
        ):
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                pooled = await svc.claim_from_pool(resolved_image, session_id)
                if pooled:
                    claim_result = await self._pool_claim_liveness_check(svc, pooled, session_id, expected_fingerprint)
                    if claim_result is not None:
                        logger.info(
                            "Claimed sandbox %s from pool for session %s",
                            pooled.id,
                            session_id,
                        )
                        from app.joysafeter_orchestrator.sandbox.file_injection import (
                            FileInjectionContext,
                            inject_session_files,
                        )
                        from app.joysafeter_shared.storage import get_storage

                        ctx = FileInjectionContext(
                            session_id=session_id,
                            external_id=pooled.external_id,
                            workspace_path=None,
                            provider=self._get_provider(),
                            storage=get_storage(),
                            is_pool_sandbox=True,
                        )
                        await inject_session_files(ctx)
                        return claim_result
                    # Liveness check failed; fall through to Stage 3

        # Stage 3: Create new sandbox
        return await self._create_new_sandbox(
            session_id,
            expected_fingerprint,
            agent_env,
            networking,
            engine_kind,
            resolved_image,
            project_id=project_id,
        )

    async def _create_new_sandbox(
        self,
        session_id: uuid.UUID,
        expected_fingerprint: dict,
        agent_env: dict[str, str],
        networking: Optional[dict],
        engine_kind: Optional[str],
        resolved_image: str,
        project_id: Optional[str] = None,
    ) -> dict:
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.database import AsyncSessionLocal

        workspace_path = (
            os.path.join(self._workspace_host_root, str(session_id)) if self._workspace_host_root is not None else None
        )

        # Preload memory files into the workspace before container start
        memory_mounts = await self._preload_memory(session_id, workspace_path) if workspace_path else []

        # Preload uploaded files into the workspace
        if workspace_path:
            from app.joysafeter_orchestrator.sandbox.file_injection import (
                FileInjectionContext,
                inject_session_files,
            )
            from app.joysafeter_shared.storage import get_storage

            ctx = FileInjectionContext(
                session_id=session_id,
                external_id="",
                workspace_path=workspace_path,
                provider=self._get_provider(),
                storage=get_storage(),
                is_pool_sandbox=False,
            )
            await inject_session_files(ctx)

        # Setup networking (e.g. Envoy proxy) before creating the container (Rust line 291)
        sandbox_id = uuid.UUID(str(_uuid7()))
        provider = self._get_provider()
        await provider.setup_networking(sandbox_id, networking or {})

        import secrets as _secrets

        runner_token = _secrets.token_hex(32)

        # Provision the sandbox (create + start container) BEFORE DB record
        try:
            external_id = await self._provision_sandbox(
                sandbox_id,
                resolved_image,
                agent_env,
                workspace_path,
                networking=networking,
                memory_mounts=memory_mounts,
                engine_kind=engine_kind,
                runner_token=runner_token,
                session_id=session_id,
                project_id=project_id,
            )
        except Exception as e:
            self._log_boundary_failure(
                code="SANDBOX_RESOLVER_PROVISION_FAILED",
                message="Failed to provision sandbox container",
                operation="provision_sandbox",
                error=e,
                data={
                    "sandbox_id": str(sandbox_id),
                    "session_id": str(session_id),
                    "image": resolved_image,
                    "provider": provider.__class__.__name__,
                    "project_id": project_id,
                },
            )
            await provider.teardown_networking(sandbox_id)
            raise

        # Now create the DB record with the real external_id
        try:
            sandbox_config = self._with_fingerprint(
                self._provisioning_config(
                    "container_started",
                    70,
                    "Sandbox created, waiting for runner ready",
                ),
                expected_fingerprint,
            )
            sandbox_config["runner_token"] = runner_token

            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                sandbox = await svc.create_sandbox(
                    image=resolved_image,
                    provider=self._default_provider,
                    chat_session_id=session_id,
                    workspace_path=workspace_path,
                    external_id=external_id,
                    sandbox_id=sandbox_id,
                    status="provisioning",
                    project_id=project_id,
                    config=sandbox_config,
                )

            logger.info("Provisioned sandbox %s (ext=%s)", sandbox.id, external_id)
            return {
                "sandbox_id": sandbox.id,
                "external_id": external_id,
                "status": "provisioning",
                "created": True,
            }
        except Exception as e:
            self._log_boundary_failure(
                code="SANDBOX_RESOLVER_DB_RECORD_CREATE_FAILED",
                message="Failed to create DB record for provisioned sandbox",
                operation="create_sandbox_record",
                error=e,
                data={
                    "sandbox_id": str(sandbox_id),
                    "external_id": external_id,
                    "session_id": str(session_id),
                    "image": resolved_image,
                    "project_id": project_id,
                },
            )
            # Destroy the already-provisioned container
            try:
                provider = self._get_provider()
                await provider.destroy(external_id)
            except Exception as destroy_exc:
                self._log_boundary_failure(
                    code="SANDBOX_RESOLVER_DB_FAILURE_CLEANUP_FAILED",
                    message="Failed to destroy provisioned sandbox after DB record creation failed",
                    operation="cleanup_after_db_record_create_failed",
                    error=destroy_exc,
                    data={"sandbox_id": str(sandbox_id), "external_id": external_id},
                )
            await provider.teardown_networking(sandbox_id)
            raise

    # ------------------------------------------------------------------
    # Memory preloading
    # ------------------------------------------------------------------

    async def _preload_memory(
        self,
        session_id: uuid.UUID,
        workspace_path: str,
    ) -> list[dict]:
        """Load all session memory stores and write files to workspace.

        Returns a list of MemoryMount dicts suitable for passing to
        ``_provision_sandbox()`` so the provider can bind-mount them.
        """
        from app.joysafeter_orchestrator.services import SessionService
        from app.joysafeter_shared.database import AsyncSessionLocal

        memory_mounts: list[dict] = []

        try:
            async with AsyncSessionLocal() as db:
                session_svc = SessionService(db)
                store_groups = await session_svc.list_all_memories_for_session(session_id)

            for group in store_groups:
                mount_name = group["mount_name"]
                access = group.get("access", "read_write")
                memories = group.get("memories", [])

                mount_dir = os.path.join(workspace_path, ".memory", mount_name)
                os.makedirs(mount_dir, exist_ok=True)

                for mem in memories:
                    # Strip leading '/' to prevent os.path.join returning absolute path
                    rel = mem["path"].lstrip("/")
                    if ".." in rel.split("/"):
                        logger.warning("Memory path traversal blocked: %s", mem["path"])
                        continue
                    file_path = os.path.join(mount_dir, rel)
                    real_file = os.path.realpath(file_path)
                    real_mount = os.path.realpath(mount_dir)
                    if not real_file.startswith(real_mount + os.sep) and real_file != real_mount:
                        logger.warning("Memory preload path escape blocked: %s", mem["path"])
                        continue
                    os.makedirs(os.path.dirname(file_path), exist_ok=True)
                    with open(file_path, "w", encoding="utf-8") as fh:
                        fh.write(mem.get("content", ""))

                memory_mounts.append(
                    {
                        "name": mount_name,
                        "host_path": mount_dir,
                        "access": access,
                    }
                )

                logger.debug(
                    "Preloaded %d memory files into %s for session %s",
                    len(memories),
                    mount_dir,
                    session_id,
                )
        except Exception as e:
            logger.warning(
                "Memory preload failed; continuing without memory mounts",
                extra={
                    "error": async_boundary_error_payload(
                        code="SANDBOX_RESOLVER_MEMORY_PRELOAD_FAILED",
                        message="Memory preload failed; continuing without memory mounts",
                        boundary="sandbox_resolver",
                        operation="preload_memory_mounts",
                        data={"session_id": str(session_id)},
                        detail=e.__class__.__name__,
                    )
                },
                exc_info=True,
            )

        return memory_mounts

    # ------------------------------------------------------------------
    # Pool claim liveness check
    # ------------------------------------------------------------------

    async def _pool_claim_liveness_check(
        self,
        svc,
        sandbox,
        session_id: uuid.UUID,
        fingerprint: dict,
    ) -> Optional[dict]:
        """Verify a claimed pool sandbox is actually alive.

        Returns a resolve result dict when the sandbox is usable (status
        always ``"provisioning"`` to match Rust), or ``None`` when the
        sandbox is broken and has been destroyed (caller should fall
        through to Stage 3).
        """
        provider = self._get_provider()
        if not sandbox.external_id:
            # Sandbox was pooled without a real container -- treat as broken
            logger.warning(
                "Pooled sandbox has no external_id; destroying",
                extra={
                    "error": async_boundary_error_payload(
                        code="SANDBOX_RESOLVER_POOL_MISSING_EXTERNAL_ID",
                        message="Pooled sandbox has no external_id; destroying",
                        boundary="sandbox_resolver",
                        operation="claim_pooled_sandbox",
                        data={"sandbox_id": str(sandbox.id), "session_id": str(session_id)},
                        retryable=True,
                        user_action="retry",
                    )
                },
            )
            await svc.mark_destroyed(sandbox.id)
            return None

        if not self._fingerprint_matches(sandbox, fingerprint):
            logger.info(
                "Pooled sandbox %s fingerprint differs from requested config, destroying and creating fresh",
                sandbox.id,
            )
            await self._destroy_broken_pooled(svc, provider, sandbox)
            return None

        try:
            status = await provider.status(sandbox.external_id)
        except Exception as e:
            logger.warning(
                "Cannot query status for pooled sandbox",
                extra={
                    "error": async_boundary_error_payload(
                        code="SANDBOX_RESOLVER_POOL_STATUS_QUERY_FAILED",
                        message="Cannot query status for pooled sandbox",
                        boundary="sandbox_resolver",
                        operation="query_pooled_sandbox_status",
                        data={"sandbox_id": str(sandbox.id), "external_id": str(sandbox.external_id)},
                        detail=e.__class__.__name__,
                    )
                },
                exc_info=True,
            )
            await self._destroy_broken_pooled(svc, provider, sandbox)
            return None

        if status == "running":
            await svc.update_status_and_config(
                sandbox.id,
                "provisioning",
                self._with_fingerprint(
                    self._provisioning_config(
                        "pool_claimed",
                        80,
                        "Claimed from warm pool, waiting for runner readiness",
                    ),
                    fingerprint,
                ),
            )
        elif status in ("exited", "paused"):
            await provider.start(sandbox.external_id)
            await svc.update_status_and_config(
                sandbox.id,
                "provisioning",
                self._with_fingerprint(
                    self._provisioning_config(
                        "pool_restarting",
                        75,
                        "Claimed stopped pooled sandbox, restarting runtime",
                    ),
                    fingerprint,
                ),
            )
            logger.info(
                "Restarted stopped pooled sandbox %s for session %s",
                sandbox.id,
                session_id,
            )
        else:
            # Unknown / dead status -- destroy and let caller create fresh
            logger.warning(
                "Pooled sandbox has unexpected status; destroying",
                extra={
                    "error": async_boundary_error_payload(
                        code="SANDBOX_RESOLVER_POOL_UNEXPECTED_STATUS",
                        message="Pooled sandbox has unexpected status; destroying",
                        boundary="sandbox_resolver",
                        operation="claim_pooled_sandbox",
                        data={"sandbox_id": str(sandbox.id), "session_id": str(session_id), "status": str(status)},
                        retryable=True,
                        user_action="retry",
                    )
                },
            )
            await self._destroy_broken_pooled(svc, provider, sandbox)
            return None

        return {
            "sandbox_id": sandbox.id,
            "external_id": sandbox.external_id,
            "status": "provisioning",
            "created": False,
        }

    async def _destroy_broken_pooled(self, svc, provider: SandboxProvider, sandbox) -> None:
        """Best-effort destroy of a broken pooled sandbox."""
        try:
            await provider.destroy(sandbox.external_id)
        except Exception as e:
            logger.debug(
                "Ignoring destroy error for broken sandbox %s: %s",
                sandbox.id,
                e,
            )
        await svc.mark_destroyed(sandbox.id)

    # ------------------------------------------------------------------
    # Pool provisioning (called from SandboxController._manage_pool_inner)
    # ------------------------------------------------------------------

    async def provision_pool_sandbox(
        self,
        image: Optional[str] = None,
        engine_kind: Optional[str] = None,
    ) -> dict:
        """Create and start a real sandbox container for the warm pool.

        Matches Rust create_pooled: container first, then DB record as "pooled".
        """
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_shared.database import AsyncSessionLocal

        if image:
            resolved_image = image
        elif engine_kind:
            resolved_image = image_for_provider(engine_kind, self._default_image)
        else:
            resolved_image = self._default_image

        sandbox_id = uuid.UUID(str(_uuid7()))
        workspace_path = (
            os.path.join(self._workspace_host_root, str(sandbox_id)) if self._workspace_host_root is not None else None
        )

        pool_env = dict(self._pool_env)
        pool_env["JOYSAFETER_SANDBOX_ID"] = str(sandbox_id)
        pool_env["JOYSAFETER_ORCHESTRATOR_URL"] = self._grpc_public_url
        pool_env["JOYSAFETER_SANDBOX_ID"] = str(sandbox_id)
        pool_env["JOYSAFETER_ORCHESTRATOR_URL"] = self._grpc_public_url

        import secrets as _secrets

        pool_runner_token = _secrets.token_hex(32)
        pool_env["JOYSAFETER_RUNNER_TOKEN"] = pool_runner_token
        pool_env["JOYSAFETER_RUNNER_TOKEN"] = pool_runner_token

        # Step 1: Create container FIRST (Rust: provider.create then store.create)
        external_id = await self._provision_sandbox(
            sandbox_id,
            resolved_image,
            env=pool_env,
            workspace_path=workspace_path,
            runner_token=pool_runner_token,
        )

        # Step 2: Insert DB record as "pooled" with pool_warm config
        pool_warm_config = self._with_fingerprint(
            {
                "provisioning": {
                    "stage": "pool_warm",
                    "progress": 100,
                    "message": "Warm pooled sandbox ready for claim",
                    "complete": True,
                    "error": False,
                },
                "runner_token": pool_runner_token,
            },
            self._sandbox_fingerprint(resolved_image, None, engine_kind, pool_env),
        )
        try:
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                await svc.create_sandbox(
                    image=resolved_image,
                    provider=self._default_provider,
                    workspace_path=workspace_path,
                    sandbox_id=sandbox_id,
                    external_id=external_id,
                    status="pooled",
                    config=pool_warm_config,
                )
        except Exception as e:
            self._log_boundary_failure(
                code="SANDBOX_RESOLVER_POOL_DB_RECORD_CREATE_FAILED",
                message="DB write failed for pooled sandbox",
                operation="create_pool_sandbox_record",
                error=e,
                data={"sandbox_id": str(sandbox_id), "external_id": external_id, "image": resolved_image},
            )
            try:
                provider = self._get_provider()
                await provider.destroy(external_id)
            except Exception as destroy_exc:
                self._log_boundary_failure(
                    code="SANDBOX_RESOLVER_POOL_DB_FAILURE_CLEANUP_FAILED",
                    message="Failed to destroy pooled sandbox after DB write failed",
                    operation="cleanup_after_pool_db_record_create_failed",
                    error=destroy_exc,
                    data={"sandbox_id": str(sandbox_id), "external_id": external_id},
                )
            raise

        logger.info("Pool sandbox %s provisioned (ext=%s)", sandbox_id, external_id)
        return {
            "sandbox_id": sandbox_id,
            "external_id": external_id,
            "status": "pooled",
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _find_stopped_for_session(self, svc, session_id: uuid.UUID):
        from sqlalchemy import and_, select

        from app.joysafeter_domain.models.joysafeter_sandbox import JoySafeterSandbox

        result = await svc.db.execute(
            select(JoySafeterSandbox).where(
                and_(
                    JoySafeterSandbox.chat_session_id == session_id,
                    JoySafeterSandbox.status == "stopped",
                    JoySafeterSandbox.destroyed_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    def _get_provider(self) -> SandboxProvider:
        if self._provider:
            return self._provider
        from app.joysafeter_orchestrator.sandbox.docker_provider import DockerSandboxProvider

        return DockerSandboxProvider()

    async def _restart_sandbox(self, svc, sandbox) -> bool:
        try:
            provider = self._get_provider()
            await provider.start(sandbox.external_id)
            await svc.update_status_and_config(
                sandbox.id,
                "provisioning",
                self._provisioning_config(
                    "runtime_restarting",
                    75,
                    "Sandbox restarted, waiting for runner to reconnect",
                ),
            )
            await svc.touch(sandbox.id)
            logger.info("Restarted stopped sandbox %s", sandbox.id)
            return True
        except Exception as e:
            self._log_boundary_failure(
                code="SANDBOX_RESOLVER_RESTART_FAILED",
                message="Failed to restart stopped sandbox",
                operation="restart_stopped_sandbox",
                error=e,
                data={"sandbox_id": str(sandbox.id), "external_id": str(sandbox.external_id)},
            )
            await svc.mark_destroyed(sandbox.id)
            return False

    async def _provision_sandbox(
        self,
        sandbox_id: uuid.UUID,
        image: str,
        env: dict[str, str],
        workspace_path: Optional[str],
        networking: Optional[dict] = None,
        memory_mounts: Optional[list[dict]] = None,
        engine_kind: Optional[str] = None,
        runner_token: Optional[str] = None,
        session_id: Optional[uuid.UUID] = None,
        project_id: Optional[str] = None,
    ) -> str:
        if workspace_path:
            os.makedirs(workspace_path, mode=0o777, exist_ok=True)
            os.chmod(workspace_path, 0o777)

        # Inject orchestrator env vars (matches Rust create_new / create_pooled)
        env = dict(env)  # copy to avoid mutating caller's dict
        env["JOYSAFETER_SANDBOX_ID"] = str(sandbox_id)
        env["JOYSAFETER_ORCHESTRATOR_URL"] = self._grpc_public_url
        env["JOYSAFETER_SANDBOX_ID"] = str(sandbox_id)
        env["JOYSAFETER_ORCHESTRATOR_URL"] = self._grpc_public_url

        if runner_token is None:
            import secrets as _secrets

            runner_token = _secrets.token_hex(32)
        env["JOYSAFETER_RUNNER_TOKEN"] = runner_token
        env["JOYSAFETER_RUNNER_TOKEN"] = runner_token

        provider = self._get_provider()
        name = str(sandbox_id)
        labels = {
            "joysafeter.sandbox_id": str(sandbox_id),
            "joysafeter.managed": "true",
        }
        if session_id is not None:
            labels["joysafeter.session_id"] = str(session_id)

        # Resolve the per-sandbox CPU/memory ceiling (global default, or the
        # owning project's override) so one tenant cannot exhaust host resources
        # on the shared fleet. A project-agnostic warm-pool sandbox (project_id
        # None) uses the global defaults without a DB read.
        from app.joysafeter_orchestrator.sandbox.resource_limits import (
            SandboxResourceLimits,
            resolve_project_sandbox_limits,
        )

        if project_id is None:
            limits = SandboxResourceLimits(
                cpu=joysafeter_config.sandbox_cpu,
                memory_mb=joysafeter_config.sandbox_memory_mb,
            )
        else:
            from app.joysafeter_shared.database import AsyncSessionLocal

            async with AsyncSessionLocal() as limits_db:
                limits = await resolve_project_sandbox_limits(
                    limits_db,
                    project_id,
                    default_cpu=joysafeter_config.sandbox_cpu,
                    default_memory_mb=joysafeter_config.sandbox_memory_mb,
                )

        external_id = await provider.create(
            name=name,
            image=image,
            env=env,
            work_dir=workspace_path or "",
            labels=labels,
            networking=networking,
            memory_mounts=memory_mounts,
            cpu=limits.cpu,
            memory_mb=limits.memory_mb,
        )
        return external_id
