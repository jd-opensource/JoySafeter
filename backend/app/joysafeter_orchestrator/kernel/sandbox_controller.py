import asyncio
import logging
import uuid
from typing import Optional

from app.joysafeter_shared.config.settings import joysafeter_config
from app.joysafeter_orchestrator.kernel.queue import QueueBackend
from app.joysafeter_orchestrator.kernel.sandbox_bridge import SandboxBridgeRegistry
from app.joysafeter_orchestrator.sandbox.provider import SandboxProvider

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

    async def cleanup_orphaned_provider_sandboxes(self) -> int:
        """Destroy provider sandboxes that have no DB record.

        This covers the crash window after provider.create succeeds but before
        joysafeter_sandboxes is committed.
        """
        try:
            active = await self._provider.list_active()
        except Exception as e:
            logger.warning("Provider orphan scan failed: %s", e)
            return 0

        if not active:
            return 0

        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService

        cleaned = 0
        for item in active:
            external_id = item.get("name") or item.get("id")
            if not external_id:
                continue
            labels = item.get("labels") or {}
            sandbox_id_raw = labels.get("joysafeter.sandbox_id")

            exists = False
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                if sandbox_id_raw:
                    try:
                        exists = await svc.get_sandbox(uuid.UUID(sandbox_id_raw)) is not None
                    except ValueError:
                        exists = False
                if not exists:
                    exists = await svc.get_sandbox_by_external_id(external_id) is not None

            if exists:
                continue

            try:
                await self._provider.destroy(external_id)
                cleaned += 1
                logger.info("Destroyed orphaned provider sandbox %s", external_id)
            except Exception as e:
                logger.warning("Failed to destroy orphaned sandbox %s: %s", external_id, e)

        return cleaned

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
        if not joysafeter_config.sandbox_pool_enabled:
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

        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService

        for bridge in bridges:
            try:
                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    record = await svc.get_sandbox(bridge.sandbox_db_id)
                    if not record or record.status in ("destroyed", "stopped", "stopping"):
                        continue

                # Skip health check if bridge has active gRPC connection or pending HITL
                if bridge.runner_connected.is_set() or bridge._requires_action_pending:
                    continue

                is_running = False
                try:
                    status = await self._provider.status(bridge.external_id)
                    is_running = status == "running"
                except Exception:
                    # Provider error: treat as dead (Rust matches on Err => cleanup)
                    is_running = False

                if not is_running:
                    logger.warning(
                        "Sandbox %s container %s not running, cleaning up",
                        bridge.sandbox_db_id,
                        bridge.external_id,
                    )
                    await self._bridge_registry.remove(bridge.sandbox_db_id)

                    try:
                        await self._provider.destroy(bridge.external_id)
                    except Exception as e:
                        logger.warning(
                            "provider.destroy(%s) failed during health check: %s",
                            bridge.external_id, e,
                        )

                    async with AsyncSessionLocal() as db:
                        svc = SandboxService(db)
                        await svc.mark_destroyed(bridge.sandbox_db_id)

                    try:
                        await self._provider.teardown_networking(bridge.sandbox_db_id)
                    except Exception as e:
                        logger.warning(
                            "Phase 0 teardown_networking for %s failed: %s",
                            bridge.sandbox_db_id, e,
                        )

                    await self._queue.drain_and_requeue_sandbox(bridge.sandbox_db_id)
            except Exception as e:
                logger.warning(
                    "Health check for sandbox %s failed: %s",
                    bridge.sandbox_db_id,
                    e,
                )

    # -- Phase 1: Expire idle sandboxes with actual provider.stop() --

    async def _expire_idle_sandboxes(self) -> None:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_domain.models.sandbox import JoySafeterSandbox
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from sqlalchemy import select, and_, text

        async with AsyncSessionLocal() as db:
            from app.joysafeter_orchestrator.lifespan import get_runtime_config
            rc = get_runtime_config()
            idle_timeout = rc.idle_timeout_sec if rc else joysafeter_config.sandbox_idle_timeout
            result = await db.execute(
                select(JoySafeterSandbox).where(
                    and_(
                        JoySafeterSandbox.status == "idle",
                        text(
                            "last_used_at < NOW() - make_interval(secs => :timeout)"
                        ),
                    )
                ).params(timeout=idle_timeout)
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
                    from app.joysafeter_shared.config.settings import joysafeter_config as _cfg

                    owner = await self._coordinator.get_sandbox_owner(sb_id)
                    if owner and owner != _cfg.instance_id:
                        return

                from app.joysafeter_shared.database import AsyncSessionLocal
                from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService

                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    cas_ok = await svc.update_status_cas(sb_id, "idle", "stopping")
                    if not cas_ok:
                        return

                bridge = await self._bridge_registry.get(sb_id)
                if bridge:
                    from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
                    shutdown_msg = joysafeter_pb2.OrchestratorMessage(
                        shutdown=joysafeter_pb2.Shutdown(
                            reason="idle timeout",
                        )
                    )
                    try:
                        bridge.runner_tx.put_nowait(shutdown_msg)
                    except asyncio.QueueFull:
                        pass
                    await self._bridge_registry.remove(sb_id)

                await asyncio.sleep(3)

                try:
                    await self._provider.stop(external_id)
                except Exception as e:
                    err = str(e)
                    if "No such container" in err:
                        async with AsyncSessionLocal() as db:
                            svc = SandboxService(db)
                            await svc.update_status(sb_id, "stopped")
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
                    await svc.update_status(sb_id, "stopped")

                logger.info("Sandbox %s stopped after idle expiry", sb_id)

        tasks = [
            asyncio.create_task(_stop_one(sb_id, ext_id))
            for sb_id, ext_id in sandboxes
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    # -- Phase 2: Force-stop sandboxes stuck in "stopping" --

    async def _force_stop_stuck(self) -> None:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_domain.models.sandbox import JoySafeterSandbox
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from sqlalchemy import select, and_, text

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JoySafeterSandbox).where(
                    and_(
                        JoySafeterSandbox.status == "stopping",
                        text("last_used_at < NOW() - make_interval(secs => :timeout)"),
                    )
                ).params(timeout=60)
            )
            stuck = [
                (sb.id, sb.external_id) for sb in result.scalars().all()
            ]

        async def _force_stop_one(sb_id: uuid.UUID, external_id: str) -> None:
            async with self._stop_semaphore:
                logger.warning(
                    "Sandbox %s stuck stopping >60s, force stopping", sb_id
                )
                await self._bridge_registry.remove(sb_id)

                stop_succeeded = False
                try:
                    await self._provider.stop(external_id)
                    stop_succeeded = True
                except Exception as e:
                    err = str(e)
                    if "No such container" in err:
                        stop_succeeded = True  # container already gone
                    else:
                        logger.warning(
                            "Force stop failed for %s: %s", sb_id, e
                        )

                if stop_succeeded:
                    async with AsyncSessionLocal() as db:
                        svc = SandboxService(db)
                        await svc.update_status(sb_id, "stopped")

                    try:
                        await self._provider.teardown_networking(sb_id)
                    except Exception as e:
                        logger.warning(
                            "Phase 2 teardown_networking for %s failed: %s", sb_id, e
                        )

        tasks = [
            asyncio.create_task(_force_stop_one(sb_id, ext_id))
            for sb_id, ext_id in stuck
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- Phase 3: Destroy stopped sandboxes past TTL --

    async def _destroy_stopped_sandboxes(self) -> None:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_domain.models.sandbox import JoySafeterSandbox
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from sqlalchemy import select, and_, text

        from app.joysafeter_orchestrator.lifespan import get_runtime_config
        rc = get_runtime_config()
        stopped_ttl = rc.stopped_max_age_sec if rc else joysafeter_config.sandbox_stopped_ttl
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JoySafeterSandbox).where(
                    and_(
                        JoySafeterSandbox.status == "stopped",
                        text(
                            "last_used_at < NOW() - make_interval(secs => :ttl)"
                        ),
                    )
                ).params(ttl=stopped_ttl)
            )
            sandboxes = [
                (sb.id, sb.external_id) for sb in result.scalars().all()
            ]

        async def _destroy_one(sb_id: uuid.UUID, external_id: str) -> None:
            async with self._stop_semaphore:
                destroy_ok = False
                try:
                    await self._provider.destroy(external_id)
                    destroy_ok = True
                except Exception as e:
                    err = str(e)
                    if "No such container" in err or "404" in err:
                        destroy_ok = True
                    else:
                        logger.warning(
                            "provider.destroy(%s) failed: %s", external_id, e
                        )

                if destroy_ok:
                    async with AsyncSessionLocal() as db:
                        svc = SandboxService(db)
                        await svc.mark_destroyed(sb_id)

                    try:
                        await self._provider.teardown_networking(sb_id)
                    except Exception as e:
                        logger.warning(
                            "Phase 3 teardown_networking for %s failed: %s", sb_id, e
                        )

                    logger.info("Sandbox %s destroyed", sb_id)

        tasks = [
            asyncio.create_task(_destroy_one(sb_id, ext_id))
            for sb_id, ext_id in sandboxes
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- Provisioning poll (unchanged logic) --

    async def _check_provisioning_timeout(self) -> None:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_domain.models.task import JoySafeterTask, JoySafeterTaskStatus
        from app.joysafeter_domain.models.sandbox import JoySafeterSandbox
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from app.joysafeter_orchestrator.services import TaskService
        from sqlalchemy import and_, select

        async def _requeue_scheduling_tasks(sandbox_id) -> int:
            try:
                await self._queue.drain_sandbox(sandbox_id)
            except Exception as e:
                logger.warning(
                    "Failed to drain sandbox queue before provisioning task recovery for %s: %s",
                    sandbox_id,
                    e,
                )

            async with AsyncSessionLocal() as db:
                task_ids = list(
                    (
                        await db.execute(
                            select(JoySafeterTask.id).where(
                                and_(
                                    JoySafeterTask.sandbox_id == sandbox_id,
                                    JoySafeterTask.status == JoySafeterTaskStatus.SCHEDULING.value,
                                )
                            )
                        )
                    ).scalars().all()
                )
                task_svc = TaskService(db)
                count = await task_svc.reset_sandbox_tasks_to_pending(sandbox_id)
            if count:
                for task_id in task_ids:
                    try:
                        await self._queue.push_to_global(task_id)
                    except Exception as e:
                        logger.warning(
                            "Failed to requeue task %s after sandbox %s provisioning failure: %s",
                            task_id,
                            sandbox_id,
                            e,
                        )
            return count

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(JoySafeterSandbox).where(
                    JoySafeterSandbox.status == "provisioning",
                )
            )
            provisioning = list(result.scalars().all())

        for sandbox in provisioning:
            # Bridge fast-path: if bridge already registered, transition to idle
            bridge = await self._bridge_registry.get(sandbox.id)
            if bridge:
                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    transitioned = await svc.update_status_cas(sandbox.id, "provisioning", "idle")
                    if transitioned:
                        await svc.touch(sandbox.id)
                        logger.info("Provisioning sandbox %s -> idle (bridge registered)", sandbox.id)
                continue

            # Check timeouts: 180s relative (last_used_at) OR 300s absolute (created_at)
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            age_from_last_used = (now - sandbox.last_used_at).total_seconds() if sandbox.last_used_at else 999
            absolute_age = (now - sandbox.created_at).total_seconds() if sandbox.created_at else 999

            if age_from_last_used <= 180 and absolute_age <= 300:
                # Not timed out yet; check provisioning_status from provider
                if sandbox.external_id:
                    try:
                        pstatus = await self._provider.provisioning_status(
                            sandbox.external_id
                        )
                    except Exception:
                        pstatus = None

                    if pstatus is not None:
                        if pstatus.get("error"):
                            logger.error(
                                "Sandbox %s provisioning failed: %s",
                                sandbox.id,
                                pstatus.get("error_message"),
                            )
                            try:
                                await self._provider.stop(sandbox.external_id)
                            except Exception as e:
                                logger.warning(
                                    "Failed to stop errored sandbox %s: %s",
                                    sandbox.id, e,
                                )
                            async with AsyncSessionLocal() as db:
                                svc = SandboxService(db)
                                await svc.update_status(sandbox.id, "stopped")
                            requeued = await _requeue_scheduling_tasks(sandbox.id)
                            if requeued:
                                logger.warning(
                                    "Requeued %d scheduling task(s) after provisioning failure for sandbox %s",
                                    requeued,
                                    sandbox.id,
                                )
                        else:
                            config = {
                                "provisioning": {
                                    "stage": pstatus.get("stage", "unknown"),
                                    "progress": pstatus.get("progress", 0),
                                    "message": pstatus.get("message", ""),
                                    "complete": pstatus.get("complete", False),
                                    "error": False,
                                }
                            }
                            async with AsyncSessionLocal() as db:
                                svc = SandboxService(db)
                                await svc.update_status_and_config(
                                    sandbox.id, "provisioning", config
                                )
                continue

            logger.error(
                "Provisioning sandbox %s timed out, stopping container",
                sandbox.id,
            )
            if sandbox.external_id:
                try:
                    await self._provider.stop(sandbox.external_id)
                except Exception as e:
                    logger.warning(
                        "Failed to stop timed-out sandbox %s: %s", sandbox.id, e
                    )
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                await svc.update_status(sandbox.id, "stopped")
            requeued = await _requeue_scheduling_tasks(sandbox.id)
            if requeued:
                logger.warning(
                    "Requeued %d scheduling task(s) after provisioning timeout for sandbox %s",
                    requeued,
                    sandbox.id,
                )

    # -- Pool manager (unchanged logic) --

    async def _manage_pool(self) -> None:
        # HA: only one instance manages the pool at a time
        if self._coordinator:
            acquired = await self._coordinator.try_acquire_lock(
                "joysafeter:lock:pool_manager", 60
            )
            if not acquired:
                return
        try:
            await self._manage_pool_inner()
        finally:
            if self._coordinator:
                await self._coordinator.release_lock("joysafeter:lock:pool_manager")

    async def _manage_pool_inner(self) -> None:
        from app.joysafeter_shared.database import AsyncSessionLocal
        from app.joysafeter_domain.models.sandbox import JoySafeterSandbox
        from app.joysafeter_orchestrator.services import SandboxRecordService as SandboxService
        from sqlalchemy import select, func, and_, text

        from app.joysafeter_orchestrator.lifespan import get_runtime_config, get_sandbox_resolver
        rc = get_runtime_config()
        min_size = rc.pool_min_size if rc else joysafeter_config.sandbox_pool_min_size
        max_age = rc.pool_max_age_sec if rc else joysafeter_config.sandbox_pool_max_age

        resolver = get_sandbox_resolver()
        if not resolver:
            logger.warning("Pool manager: no sandbox resolver available, skipping")
            return

        pool_images = joysafeter_config.sandbox_pool_images
        if not pool_images:
            pool_images = [joysafeter_config.sandbox_image]

        for image in pool_images:
            async with AsyncSessionLocal() as db:
                svc = SandboxService(db)
                pool_count = await svc.count_pool_by_provider_image(
                    joysafeter_config.sandbox_provider, image
                )

            deficit = min_size - pool_count
            if deficit > 0:
                logger.info("Topping up pool for image=%s (count=%d, deficit=%d)", image, pool_count, deficit)
                for _ in range(deficit):
                    try:
                        await resolver.provision_pool_sandbox(image=image)
                        logger.info("Created pooled sandbox for image=%s", image)
                    except Exception as e:
                        logger.warning("Failed to provision pool sandbox for image=%s: %s", image, e)
                        break

        # Destroy stale pooled sandboxes
        async with AsyncSessionLocal() as db:
            stale_result = await db.execute(
                select(JoySafeterSandbox).where(
                    and_(
                        JoySafeterSandbox.status == "pooled",
                        text(
                            "created_at < NOW() - make_interval(secs => :max_age)"
                        ),
                    )
                ).params(max_age=max_age)
            )
            stale_pooled = [
                (sb.id, sb.external_id) for sb in stale_result.scalars().all()
            ]

        for sb_id, external_id in stale_pooled:
            logger.info("Destroying stale pooled sandbox %s", sb_id)
            destroy_ok = False
            if external_id:
                try:
                    await self._provider.destroy(external_id)
                    destroy_ok = True
                except Exception as e:
                    err = str(e)
                    if "No such container" in err or "404" in err:
                        destroy_ok = True
                    else:
                        logger.warning("Pool stale destroy(%s) failed: %s", external_id, e)
            else:
                destroy_ok = True

            if destroy_ok:
                async with AsyncSessionLocal() as db:
                    svc = SandboxService(db)
                    await svc.mark_destroyed(sb_id)
