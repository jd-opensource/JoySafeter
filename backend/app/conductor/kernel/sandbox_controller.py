import asyncio
import logging
import uuid
from typing import Optional

from app.conductor.config import conductor_config
from app.conductor.kernel.queue import QueueBackend
from app.conductor.kernel.sandbox_bridge import SandboxBridgeRegistry
from app.conductor.sandbox.provider import SandboxProvider

logger = logging.getLogger(__name__)

MAX_CONCURRENT_STOPS = 10


class SandboxController:
    def __init__(
        self,
        queue: QueueBackend,
        bridge_registry: SandboxBridgeRegistry,
        provider: SandboxProvider,
        envoy_manager=None,
        coordinator=None,
    ):
        self._queue = queue
        self._bridge_registry = bridge_registry
        self._provider = provider
        self._envoy_manager = envoy_manager
        self._coordinator = coordinator
        self._stop_semaphore = asyncio.Semaphore(MAX_CONCURRENT_STOPS)

    async def run_idle_sweep(self) -> None:
        logger.info("SandboxController idle sweep started (30s interval)")
        while True:
            await asyncio.sleep(30)
            try:
                await self._health_check_bridges()
            except Exception as e:
                logger.warning("Phase 0 health check failed: %s", e)
            try:
                await self._expire_idle_sandboxes()
            except Exception as e:
                logger.warning("Phase 1 idle expiry failed: %s", e)
            try:
                await self._force_stop_stuck()
            except Exception as e:
                logger.warning("Phase 2 stuck stopping failed: %s", e)
            try:
                await self._destroy_stopped_sandboxes()
            except Exception as e:
                logger.warning("Phase 3 destroy failed: %s", e)

    async def run_provisioning_poll(self) -> None:
        logger.info("SandboxController provisioning poll started (5s interval)")
        while True:
            await asyncio.sleep(5)
            try:
                await self._check_provisioning_timeout()
            except Exception as e:
                logger.warning("Provisioning poll failed: %s", e)

    async def run_pool_manager(self) -> None:
        if not conductor_config.sandbox_pool_enabled:
            return
        logger.info("SandboxController pool manager started (30s interval)")
        while True:
            await asyncio.sleep(30)
            try:
                await self._manage_pool()
            except Exception as e:
                logger.warning("Pool manager failed: %s", e)

    # -- Phase 0: Health check all registered bridges --

    async def _health_check_bridges(self) -> None:
        bridges = self._bridge_registry.all_bridges()
        if not bridges:
            return

        for bridge in bridges:
            try:
                status = await self._provider.status(bridge.external_id)
                if status not in ("running", "created"):
                    logger.warning(
                        "Sandbox %s container %s dead (status=%s), cleaning up",
                        bridge.sandbox_db_id,
                        bridge.external_id,
                        status,
                    )
                    await self._bridge_registry.remove(bridge.sandbox_db_id)
                    await self._queue.drain_and_requeue_sandbox(bridge.sandbox_db_id)

                    from app.core.database import AsyncSessionLocal
                    from app.conductor.services.sandbox_service import SandboxService

                    async with AsyncSessionLocal() as db:
                        svc = SandboxService(db)
                        if not await svc.update_status_cas(
                            bridge.sandbox_db_id, "running", "stopped"
                        ):
                            await svc.update_status_cas(
                                bridge.sandbox_db_id, "idle", "stopped"
                            )
            except Exception as e:
                logger.warning(
                    "Health check for sandbox %s failed: %s",
                    bridge.sandbox_db_id,
                    e,
                )

    # -- Phase 1: Expire idle sandboxes with actual provider.stop() --

    async def _expire_idle_sandboxes(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.sandbox import ConductorSandbox
        from app.conductor.services.sandbox_service import SandboxService
        from sqlalchemy import select, and_, text

        async with AsyncSessionLocal() as db:
            from app.conductor.lifespan import get_runtime_config
            rc = get_runtime_config()
            idle_timeout = rc.idle_timeout_sec if rc else conductor_config.sandbox_idle_timeout
            result = await db.execute(
                select(ConductorSandbox).where(
                    and_(
                        ConductorSandbox.status.in_(["running", "idle"]),
                        text(
                            f"last_used_at < NOW() - INTERVAL '{idle_timeout} seconds'"
                        ),
                    )
                )
            )
            sandboxes = [
                (sb.id, sb.external_id) for sb in result.scalars().all()
            ]

        if not sandboxes:
            return

        async def _stop_one(sb_id: uuid.UUID, external_id: str) -> None:
            async with self._stop_semaphore:
                # HA: skip sandboxes owned by another instance
                if self._coordinator:
                    from app.conductor.config import conductor_config as _cfg

                    owner = await self._coordinator.get_sandbox_owner(sb_id)
                    if owner and owner != _cfg.instance_id:
                        return

                from app.core.database import AsyncSessionLocal
                from app.conductor.services.sandbox_service import SandboxService

                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    cas_ok = await svc.update_status_cas(sb_id, "idle", "stopping")
                    if not cas_ok:
                        cas_ok = await svc.update_status_cas(
                            sb_id, "running", "stopping"
                        )
                    if not cas_ok:
                        return

                bridge = await self._bridge_registry.get(sb_id)
                if bridge:
                    bridge.request_cancel()

                await self._queue.drain_and_requeue_sandbox(sb_id)
                await asyncio.sleep(3)

                await self._bridge_registry.remove(sb_id)

                try:
                    await self._provider.stop(external_id)
                except Exception as e:
                    err = str(e).lower()
                    if "no such container" in err or "not found" in err:
                        pass
                    else:
                        logger.warning(
                            "provider.stop(%s) failed: %s, reverting to idle",
                            external_id,
                            e,
                        )
                        async with AsyncSessionLocal() as db:
                            svc = SandboxService(db)
                            await svc.update_status_cas(
                                sb_id, "stopping", "idle"
                            )
                        return

                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    await svc.update_status_cas(sb_id, "stopping", "stopped")

                if self._coordinator:
                    await self._coordinator.remove_sandbox_owner(sb_id)

                logger.info("Sandbox %s stopped after idle expiry", sb_id)

        tasks = [
            asyncio.create_task(_stop_one(sb_id, ext_id))
            for sb_id, ext_id in sandboxes
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- Phase 2: Force-stop sandboxes stuck in "stopping" --

    async def _force_stop_stuck(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.sandbox import ConductorSandbox
        from app.conductor.services.sandbox_service import SandboxService
        from sqlalchemy import select, and_, text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConductorSandbox).where(
                    and_(
                        ConductorSandbox.status == "stopping",
                        text("updated_at < NOW() - INTERVAL '60 seconds'"),
                    )
                )
            )
            stuck = [
                (sb.id, sb.external_id) for sb in result.scalars().all()
            ]

        for sb_id, external_id in stuck:
            async with self._stop_semaphore:
                logger.warning(
                    "Sandbox %s stuck stopping >60s, force stopping", sb_id
                )
                await self._bridge_registry.remove(sb_id)

                try:
                    await self._provider.stop(external_id)
                except Exception as e:
                    err = str(e).lower()
                    if "no such container" not in err and "not found" not in err:
                        logger.warning(
                            "Force stop failed for %s: %s", sb_id, e
                        )

                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    await svc.update_status_cas(sb_id, "stopping", "stopped")

    # -- Phase 3: Destroy stopped sandboxes past TTL --

    async def _destroy_stopped_sandboxes(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.sandbox import ConductorSandbox
        from app.conductor.services.sandbox_service import SandboxService
        from sqlalchemy import select, and_, text

        from app.conductor.lifespan import get_runtime_config
        rc = get_runtime_config()
        stopped_ttl = rc.stopped_max_age_sec if rc else conductor_config.sandbox_stopped_ttl
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(ConductorSandbox).where(
                    and_(
                        ConductorSandbox.status == "stopped",
                        text(
                            f"updated_at < NOW() - INTERVAL '{stopped_ttl} seconds'"
                        ),
                    )
                )
            )
            sandboxes = [
                (sb.id, sb.external_id) for sb in result.scalars().all()
            ]

        for sb_id, external_id in sandboxes:
            async with self._stop_semaphore:
                try:
                    await self._provider.destroy(external_id)
                except Exception as e:
                    err = str(e).lower()
                    if "no such container" not in err and "not found" not in err:
                        logger.warning(
                            "provider.destroy(%s) failed: %s", external_id, e
                        )

                if self._envoy_manager:
                    try:
                        await self._envoy_manager.remove_sandbox(sb_id)
                    except Exception as e:
                        logger.warning(
                            "Envoy teardown for %s failed: %s", sb_id, e
                        )

                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    await svc.update_status_cas(sb_id, "stopped", "destroyed")

                logger.info("Sandbox %s destroyed", sb_id)

    # -- Provisioning poll (unchanged logic) --

    async def _check_provisioning_timeout(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.sandbox import ConductorSandbox
        from sqlalchemy import update, and_, text

        async with AsyncSessionLocal() as db:
            await db.execute(
                update(ConductorSandbox)
                .where(
                    and_(
                        ConductorSandbox.status == "provisioning",
                        text("created_at < NOW() - INTERVAL '5 minutes'"),
                    )
                )
                .values(status="stopped")
            )
            await db.commit()

    # -- Pool manager (unchanged logic) --

    async def _manage_pool(self) -> None:
        # HA: only one instance manages the pool at a time
        if self._coordinator:
            acquired = await self._coordinator.try_acquire_lock(
                "conductor:lock:pool_manager", 60
            )
            if not acquired:
                return
        try:
            await self._manage_pool_inner()
        finally:
            if self._coordinator:
                await self._coordinator.release_lock("conductor:lock:pool_manager")

    async def _manage_pool_inner(self) -> None:
        from app.core.database import AsyncSessionLocal
        from app.conductor.models.sandbox import ConductorSandbox
        from app.conductor.services.sandbox_service import SandboxService
        from sqlalchemy import select, func, and_, update, text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(func.count())
                .select_from(ConductorSandbox)
                .where(ConductorSandbox.status == "pooled")
            )
            pool_count = result.scalar()

            from app.conductor.lifespan import get_runtime_config
            rc = get_runtime_config()
            min_size = rc.pool_min_size if rc else conductor_config.sandbox_pool_min_size
            deficit = min_size - pool_count
            if deficit > 0:
                svc = SandboxService(db)
                for _ in range(deficit):
                    await svc.create_sandbox(
                        image=conductor_config.sandbox_image,
                        provider=conductor_config.sandbox_provider,
                    )
                    logger.info(
                        "Pre-warmed pooled sandbox (pool deficit: %d)", deficit
                    )

            max_age = rc.pool_max_age_sec if rc else conductor_config.sandbox_pool_max_age
            await db.execute(
                update(ConductorSandbox)
                .where(
                    and_(
                        ConductorSandbox.status == "pooled",
                        text(
                            f"created_at < NOW() - INTERVAL '{max_age} seconds'"
                        ),
                    )
                )
                .values(status="stopped")
            )
            await db.commit()
