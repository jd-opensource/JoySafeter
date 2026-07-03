"""
JoySafeter Kernel Lifespan (startup/shutdown).

This module provides joysafeter_startup() and joysafeter_shutdown() functions
for integrating the JoySafeter kernel into the application lifecycle.
"""

import asyncio
import logging
import os
import signal
import threading

from app.joysafeter_shared.config.settings import JoySafeterConfig, joysafeter_config

logger = logging.getLogger(__name__)

_background_tasks: list[asyncio.Task] = []
_scheduler = None
_task_controller = None
_sandbox_controller = None
_session_broadcaster = None
_adapter_registry = None
_bridge_registry = None
_event_buffer = None
_sandbox_resolver = None
_envoy_manager = None
_memory_subscribers = None
_image_builder = None
_sandbox_provider = None
_redis_coordinator = None
_runtime_config = None
_grpc_server = None
_grpc_servicer = None
_vault_provider = None
_event_bus = None


def get_scheduler():
    return _scheduler


def get_session_broadcaster():
    return _session_broadcaster


def ensure_session_broadcaster(redis_client=None, instance_id: str | None = None):
    """Ensure a lightweight SessionBroadcaster exists for API-only service roles.

    In split-service deployments the API process does not run the full
    orchestrator startup, but it still owns the SSE endpoint and must subscribe
    to Redis session events.  This initializes only the broadcaster without
    starting scheduler / sandbox / gRPC components.
    """
    global _session_broadcaster
    if _session_broadcaster is None:
        from app.joysafeter_orchestrator.session_broadcaster import SessionBroadcaster

        _session_broadcaster = SessionBroadcaster(
            redis_client=redis_client,
            instance_id=instance_id or joysafeter_config.instance_id,
        )
        logger.info("   SessionBroadcaster initialized")
    return _session_broadcaster


def get_adapter_registry():
    return _adapter_registry


def get_bridge_registry():
    return _bridge_registry


def get_event_buffer():
    return _event_buffer


def get_sandbox_resolver():
    return _sandbox_resolver


def get_envoy_manager():
    return _envoy_manager


def get_memory_subscribers():
    return _memory_subscribers


def get_image_builder():
    return _image_builder


def get_sandbox_provider():
    return _sandbox_provider


def get_redis_coordinator():
    return _redis_coordinator


def get_runtime_config():
    return _runtime_config


def get_grpc_servicer():
    return _grpc_servicer


def get_vault_provider():
    return _vault_provider


def get_event_bus():
    return _event_bus


def _create_sandbox_provider():
    from app.joysafeter_orchestrator.sandbox.docker_provider import DockerSandboxProvider

    provider_name = joysafeter_config.sandbox_provider.lower().strip()
    if provider_name not in {"docker", "daytona", "e2b"}:
        raise RuntimeError(
            "Unsupported JOYSAFETER_SANDBOX_PROVIDER=%r. Expected docker, daytona, or e2b."
            % joysafeter_config.sandbox_provider
        )
    if provider_name == "daytona":
        from app.joysafeter_orchestrator.sandbox.daytona_provider import DaytonaSandboxProvider

        if not joysafeter_config.daytona_api_url or not joysafeter_config.daytona_api_key:
            raise RuntimeError(
                "JOYSAFETER_DAYTONA_API_URL and JOYSAFETER_DAYTONA_API_KEY are required when JOYSAFETER_SANDBOX_PROVIDER=daytona"
            )
        return DaytonaSandboxProvider(
            api_url=joysafeter_config.daytona_api_url,
            api_key=joysafeter_config.daytona_api_key,
            target=joysafeter_config.daytona_target if joysafeter_config.daytona_target is not None else "us",
            snapshot=joysafeter_config.daytona_snapshot,
        )
    elif provider_name == "e2b":
        from app.joysafeter_orchestrator.sandbox.e2b_provider import E2bSandboxProvider

        if not joysafeter_config.e2b_api_key or not joysafeter_config.e2b_template_id:
            raise RuntimeError(
                "JOYSAFETER_E2B_API_KEY and JOYSAFETER_E2B_TEMPLATE_ID are required when JOYSAFETER_SANDBOX_PROVIDER=e2b"
            )
        return E2bSandboxProvider(
            api_url=joysafeter_config.e2b_api_url
            if joysafeter_config.e2b_api_url is not None
            else "https://api.e2b.app",
            api_key=joysafeter_config.e2b_api_key,
            template_id=joysafeter_config.e2b_template_id,
        )
    return DockerSandboxProvider(
        network=joysafeter_config.envoy_network if joysafeter_config.envoy_enabled else None,
        socket_volume=joysafeter_config.envoy_socket_volume if joysafeter_config.envoy_enabled else None,
    )


def _setup_sighup_handler(runtime_config, config: JoySafeterConfig) -> None:
    """Register a SIGHUP handler that hot-reloads runtime-tunable config."""

    if threading.current_thread() is not threading.main_thread():
        logger.info("Skipping SIGHUP handler registration outside main thread")
        return

    def _handler(signum, frame):  # noqa: ARG001
        logger.info("SIGHUP received, reloading joysafeter runtime config...")
        new_cfg = JoySafeterConfig()
        runtime_config.update(
            idle_timeout_sec=new_cfg.sandbox_idle_timeout,
            stopped_max_age_sec=new_cfg.sandbox_stopped_ttl,
            heartbeat_timeout_sec=new_cfg.heartbeat_ttl,
            sandbox_failure_threshold=new_cfg.sandbox_failure_threshold,
            pool_min_size=new_cfg.sandbox_pool_min_size,
            pool_max_age_sec=new_cfg.sandbox_pool_max_age,
            event_batch_max_size=new_cfg.event_batch_max_size,
            event_batch_max_delay_ms=new_cfg.event_batch_max_delay_ms,
        )
        logger.info("Runtime config reloaded successfully")

    signal.signal(signal.SIGHUP, _handler)


async def joysafeter_startup() -> None:
    global _scheduler, _task_controller, _sandbox_controller
    global _session_broadcaster, _adapter_registry
    global _bridge_registry, _event_buffer, _sandbox_resolver
    global _envoy_manager, _memory_subscribers, _image_builder
    global _sandbox_provider, _redis_coordinator
    global _runtime_config, _grpc_server, _grpc_servicer
    global _vault_provider, _event_bus

    if not joysafeter_config.enabled:
        logger.info("JoySafeter kernel disabled")
        return

    logger.info("Starting JoySafeter kernel...")

    from app.joysafeter_orchestrator.kernel.memory_sync import MemoryStoreSubscribers
    from app.joysafeter_orchestrator.kernel.queue import InMemoryRedisQueueBackend
    from app.joysafeter_orchestrator.kernel.sandbox_bridge import SandboxBridgeRegistry
    from app.joysafeter_orchestrator.kernel.sandbox_controller import SandboxController
    from app.joysafeter_orchestrator.kernel.sandbox_resolver import SandboxResolver
    from app.joysafeter_orchestrator.kernel.scheduler import TaskScheduler
    from app.joysafeter_orchestrator.kernel.task_controller import TaskController
    from app.joysafeter_orchestrator.runtime.registry import AdapterRegistry
    from app.joysafeter_orchestrator.session_broadcaster import SessionBroadcaster
    from app.joysafeter_worker.events.batch_writer import EventBatchConfig, EventBatchSender

    redis_client = None
    try:
        from app.joysafeter_shared.cache.redis import RedisClient

        redis_client = RedisClient.get_client()
    except Exception:
        logger.info("Redis not available, using in-memory queue")

    # HA: Redis coordinator for cross-instance coordination (created first, queue depends on it)
    if redis_client:
        from app.joysafeter_orchestrator.kernel.redis_coordinator import RedisCoordinator

        _redis_coordinator = RedisCoordinator(redis_client, joysafeter_config.instance_id)
        await _redis_coordinator.register_instance()
        _redis_coordinator.spawn_heartbeat()
        logger.info("   RedisCoordinator registered (instance=%s)", joysafeter_config.instance_id)
    else:
        logger.info("   Redis not available, HA coordination disabled")

    # Queue: in-memory primary with optional Redis coordinator for HA (matches Rust architecture)
    queue = InMemoryRedisQueueBackend(redis_coord=_redis_coordinator)

    _scheduler = TaskScheduler(queue, joysafeter_config.max_concurrent_tasks)
    _task_controller = TaskController(queue)

    _bridge_registry = SandboxBridgeRegistry()

    _sandbox_provider = _create_sandbox_provider()
    _sandbox_controller = SandboxController(
        queue=queue,
        bridge_registry=_bridge_registry,
        provider=_sandbox_provider,
        envoy_manager=None,  # set after envoy init below
        coordinator=_redis_coordinator,
    )

    _session_broadcaster = SessionBroadcaster(
        redis_client=redis_client,
        instance_id=f"{joysafeter_config.instance_id}:orchestrator:{os.getpid()}",
    )

    _event_buffer = EventBatchSender(
        EventBatchConfig(
            enabled=joysafeter_config.event_batch_enabled,
            max_size=joysafeter_config.event_batch_max_size,
            max_delay_ms=joysafeter_config.event_batch_max_delay_ms,
        )
    )
    _event_buffer.start()

    _resolver_kwargs = dict(
        default_provider=joysafeter_config.sandbox_provider,
        default_image=joysafeter_config.sandbox_image,
        pool_enabled=joysafeter_config.sandbox_pool_enabled,
        provider=_sandbox_provider,
        grpc_public_url=joysafeter_config.grpc_public_url,
    )
    if joysafeter_config.sandbox_workspace_root is not None:
        _resolver_kwargs["workspace_host_root"] = joysafeter_config.sandbox_workspace_root

    _sandbox_resolver = SandboxResolver(**_resolver_kwargs)

    _memory_subscribers = MemoryStoreSubscribers()
    logger.info("   MemoryStoreSubscribers initialized")

    # Envoy network isolation
    if joysafeter_config.envoy_enabled:
        try:
            from app.joysafeter_orchestrator.sandbox.envoy_manager import EnvoyConfig, EnvoyManager

            _envoy_manager = EnvoyManager(
                EnvoyConfig(
                    envoy_image=joysafeter_config.envoy_image,
                    socket_volume=joysafeter_config.envoy_socket_volume,
                    config_dir=joysafeter_config.envoy_config_dir,
                    envoy_network=joysafeter_config.envoy_network,
                    grpc_target_host=joysafeter_config.envoy_grpc_host,
                    grpc_target_port=joysafeter_config.envoy_grpc_port,
                    container_name=joysafeter_config.envoy_container_name,
                )
            )
            await _envoy_manager.init()
            _sandbox_controller._envoy_manager = _envoy_manager
            if hasattr(_sandbox_provider, "_envoy_manager"):
                _sandbox_provider._envoy_manager = _envoy_manager
            logger.info("   EnvoyManager initialized")
        except Exception as e:
            logger.warning("   EnvoyManager initialization failed: %s", e)
            _envoy_manager = None
    else:
        logger.info("   Envoy network isolation disabled")

    # Image builder
    if joysafeter_config.image_builder_enabled:
        try:
            from app.joysafeter_orchestrator.sandbox.image_builder import ImageBuilder

            _image_builder = ImageBuilder(
                default_base=joysafeter_config.image_builder_base,
            )
            logger.info("   ImageBuilder initialized")
        except Exception as e:
            logger.warning("   ImageBuilder initialization failed: %s", e)
    else:
        logger.info("   Image builder disabled")

    from app.joysafeter_orchestrator.runtime_config import RuntimeConfig

    _runtime_config = RuntimeConfig(
        idle_timeout_sec=joysafeter_config.sandbox_idle_timeout,
        stopped_max_age_sec=joysafeter_config.sandbox_stopped_ttl,
        heartbeat_timeout_sec=joysafeter_config.heartbeat_ttl,
        sandbox_failure_threshold=joysafeter_config.sandbox_failure_threshold,
        pool_min_size=joysafeter_config.sandbox_pool_min_size,
        pool_max_age_sec=joysafeter_config.sandbox_pool_max_age,
        event_batch_max_size=joysafeter_config.event_batch_max_size,
        event_batch_max_delay_ms=joysafeter_config.event_batch_max_delay_ms,
    )

    _setup_sighup_handler(_runtime_config, joysafeter_config)

    # Wire RuntimeConfig into EventBatchSender for hot-reload support
    if _event_buffer:
        _event_buffer._runtime_config = _runtime_config

    _adapter_registry = await AdapterRegistry.discover()
    logger.info("Discovered adapters: %s", _adapter_registry.provider_names())

    # Vault provider (encryption layer for credential storage)
    if joysafeter_config.vault_encryption_key:
        from app.joysafeter_orchestrator.services import VaultCipher

        _vault_provider = VaultCipher(joysafeter_config.vault_encryption_key)
        logger.info(
            "   VaultCipher initialized (encryption %s)", "enabled" if _vault_provider.is_enabled else "passthrough"
        )
    else:
        logger.info("   Vault encryption key not configured, vault provider disabled")

    # Event Bus: decouple gRPC server from downstream consumers
    from app.joysafeter_orchestrator.events.bus import JoySafeterEventBus
    from app.joysafeter_orchestrator.events.session_broadcast import SessionBroadcastSubscriber
    from app.joysafeter_orchestrator.events.session_state import SessionStateSubscriber
    from app.joysafeter_orchestrator.events.task_broadcast import TaskBroadcastSubscriber

    _event_bus = JoySafeterEventBus()
    if joysafeter_config.event_stream_enabled:
        from app.joysafeter_orchestrator.events.stream_publisher import EventStreamPersistSubscriber

        _event_bus.register(EventStreamPersistSubscriber(joysafeter_config.event_stream_key, _event_buffer))
        logger.info(
            "   JoySafeter events will be persisted through Redis Stream (%s)", joysafeter_config.event_stream_key
        )
    else:
        from app.joysafeter_orchestrator.events.event_persist import EventPersistSubscriber

        _event_bus.register(EventPersistSubscriber(_event_buffer))
    _event_bus.register(SessionStateSubscriber())
    _event_bus.register(SessionBroadcastSubscriber(_session_broadcaster))
    _event_bus.register(TaskBroadcastSubscriber(_bridge_registry))
    logger.info("   JoySafeterEventBus initialized (4 subscribers)")

    # gRPC server for runner connections
    try:
        from app.joysafeter_orchestrator.grpc.server import start_grpc_server

        _grpc_server, _grpc_servicer = await start_grpc_server(
            bridge_registry=_bridge_registry,
            event_buffer=_event_buffer,
            queue=queue,
            host=joysafeter_config.grpc_host,
            port=joysafeter_config.grpc_port,
            vault_provider=_vault_provider,
            execution_semaphore=_scheduler.execution_semaphore,
            event_bus=_event_bus,
        )
    except Exception as e:
        logger.warning("Failed to start gRPC server: %s", e)

    await _task_controller.recover_on_startup()

    try:
        cleaned = await _sandbox_controller.cleanup_orphaned_provider_sandboxes()
        if cleaned:
            logger.info("Startup recovery: destroyed %d orphaned provider sandboxes", cleaned)
    except Exception as e:
        logger.warning("Startup orphan sandbox cleanup failed: %s", e)

    _background_tasks.append(asyncio.create_task(_scheduler.run(), name="joysafeter-scheduler"))
    _background_tasks.append(asyncio.create_task(_task_controller.run(), name="joysafeter-task-ctrl"))
    _background_tasks.append(asyncio.create_task(_task_controller.run_lease_manager(), name="joysafeter-task-lease"))
    _background_tasks.append(asyncio.create_task(_sandbox_controller.run_idle_sweep(), name="joysafeter-sandbox-sweep"))
    _background_tasks.append(
        asyncio.create_task(_sandbox_controller.run_provisioning_poll(), name="joysafeter-prov-poll")
    )
    _background_tasks.append(asyncio.create_task(_sandbox_controller.run_pool_manager(), name="joysafeter-pool-mgr"))

    # HA: cross-instance command listener
    if _redis_coordinator and redis_client:
        from app.joysafeter_orchestrator.kernel.command_listener import CommandListener

        cmd_listener = CommandListener(redis_client, _redis_coordinator, _bridge_registry)
        _background_tasks.append(asyncio.create_task(cmd_listener.run(), name="joysafeter-cmd-listener"))

    logger.info("JoySafeter kernel started (%d background tasks)", len(_background_tasks))


async def joysafeter_shutdown() -> None:
    if not joysafeter_config.enabled:
        return

    logger.info("Shutting down JoySafeter kernel...")

    # Send Shutdown protobuf to all connected runners (Rust main.rs lines 332-343)
    if _bridge_registry:
        from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2

        for bridge in _bridge_registry.all_bridges():
            try:
                shutdown_msg = joysafeter_pb2.OrchestratorMessage(
                    shutdown=joysafeter_pb2.Shutdown(
                        reason="orchestrator shutting down",
                    )
                )
                await bridge.write_to_runner(shutdown_msg)
            except Exception:
                pass
        logger.info("Sent Shutdown to %d sandbox bridges", _bridge_registry.count())

    if _scheduler:
        _scheduler.stop()

    if _event_buffer:
        await _event_buffer.stop()

    if _adapter_registry:
        for name in _adapter_registry.provider_names():
            adapter = _adapter_registry.get(name)
            if adapter and hasattr(adapter, "close"):
                try:
                    await adapter.close()
                except Exception as e:
                    logger.warning("Failed to close adapter %s: %s", name, e)
        logger.info("Closed all adapters")

    if _redis_coordinator:
        await _redis_coordinator.stop()

    if _grpc_server:
        await _grpc_server.stop(grace=5)
        logger.info("gRPC server stopped")

    if _sandbox_provider and hasattr(_sandbox_provider, "close"):
        await _sandbox_provider.close()

    for task in _background_tasks:
        task.cancel()

    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()

    logger.info("JoySafeter kernel shut down")
