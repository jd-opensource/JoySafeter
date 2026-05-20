import asyncio
import logging
import signal
from typing import Optional

from app.conductor.config import ConductorConfig, conductor_config

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


def get_scheduler():
    return _scheduler


def get_session_broadcaster():
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


def _create_sandbox_provider():
    from app.conductor.sandbox.docker_provider import DockerSandboxProvider

    provider_name = conductor_config.sandbox_provider
    if provider_name == "daytona":
        from app.conductor.sandbox.daytona_provider import DaytonaSandboxProvider

        return DaytonaSandboxProvider(
            api_url=conductor_config.daytona_api_url,
            api_key=conductor_config.daytona_api_key,
            target=conductor_config.daytona_target,
            snapshot=conductor_config.daytona_snapshot,
        )
    elif provider_name == "e2b":
        from app.conductor.sandbox.e2b_provider import E2bSandboxProvider

        return E2bSandboxProvider(
            api_url=conductor_config.e2b_api_url,
            api_key=conductor_config.e2b_api_key,
            template_id=conductor_config.e2b_template_id,
        )
    return DockerSandboxProvider(
        network=conductor_config.envoy_network if conductor_config.envoy_enabled else None,
        socket_volume=conductor_config.envoy_socket_volume if conductor_config.envoy_enabled else None,
    )


def _setup_sighup_handler(runtime_config, config: ConductorConfig) -> None:
    """Register a SIGHUP handler that hot-reloads runtime-tunable config."""

    def _handler(signum, frame):  # noqa: ARG001
        logger.info("SIGHUP received, reloading conductor runtime config...")
        new_cfg = ConductorConfig()
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


async def conductor_startup() -> None:
    global _scheduler, _task_controller, _sandbox_controller
    global _session_broadcaster, _adapter_registry
    global _bridge_registry, _event_buffer, _sandbox_resolver
    global _envoy_manager, _memory_subscribers, _image_builder
    global _sandbox_provider, _redis_coordinator
    global _runtime_config, _grpc_server, _grpc_servicer
    global _vault_provider

    if not conductor_config.enabled:
        logger.info("Conductor kernel disabled (CONDUCTOR_ENABLED=false)")
        return

    logger.info("Starting Conductor kernel...")

    from app.conductor.kernel.queue import InMemoryQueueBackend, RedisQueueBackend
    from app.conductor.kernel.scheduler import TaskScheduler
    from app.conductor.kernel.task_controller import TaskController
    from app.conductor.kernel.sandbox_controller import SandboxController
    from app.conductor.kernel.session_broadcaster import SessionBroadcaster
    from app.conductor.kernel.sandbox_bridge import SandboxBridgeRegistry
    from app.conductor.kernel.event_buffer import EventBatchSender, EventBatchConfig
    from app.conductor.kernel.sandbox_resolver import SandboxResolver
    from app.conductor.kernel.memory_sync import MemoryStoreSubscribers
    from app.conductor.runtime.registry import AdapterRegistry

    redis_client = None
    try:
        from app.core.redis import RedisClient
        redis_client = RedisClient.get_client()
    except Exception:
        logger.info("Redis not available, using in-memory queue")

    if redis_client:
        queue = RedisQueueBackend(redis_client, conductor_config.redis_queue_prefix)
    else:
        queue = InMemoryQueueBackend()

    # HA: Redis coordinator for cross-instance coordination
    if redis_client:
        from app.conductor.kernel.redis_coordinator import RedisCoordinator

        _redis_coordinator = RedisCoordinator(redis_client, conductor_config.instance_id)
        await _redis_coordinator.register_instance()
        _redis_coordinator.spawn_heartbeat()
        logger.info("   ✓ RedisCoordinator registered (instance=%s)", conductor_config.instance_id)
    else:
        logger.info("   Redis not available, HA coordination disabled")

    _scheduler = TaskScheduler(queue, conductor_config.max_concurrent_tasks)
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
        instance_id=conductor_config.instance_id,
    )

    _event_buffer = EventBatchSender(EventBatchConfig(
        enabled=conductor_config.event_batch_enabled,
        max_size=conductor_config.event_batch_max_size,
        max_delay_ms=conductor_config.event_batch_max_delay_ms,
    ))
    _event_buffer.start()

    _sandbox_resolver = SandboxResolver(
        default_provider=conductor_config.sandbox_provider,
        default_image=conductor_config.sandbox_image,
        pool_enabled=conductor_config.sandbox_pool_enabled,
        workspace_host_root=conductor_config.sandbox_workspace_root,
        provider=_sandbox_provider,
    )

    _memory_subscribers = MemoryStoreSubscribers()
    logger.info("   ✓ MemoryStoreSubscribers initialized")

    # Envoy network isolation
    if conductor_config.envoy_enabled:
        try:
            from app.conductor.sandbox.envoy_manager import EnvoyManager, EnvoyConfig

            _envoy_manager = EnvoyManager(EnvoyConfig(
                envoy_image=conductor_config.envoy_image,
                socket_volume=conductor_config.envoy_socket_volume,
                config_dir=conductor_config.envoy_config_dir,
                envoy_network=conductor_config.envoy_network,
                grpc_target_host=conductor_config.envoy_grpc_host,
                grpc_target_port=conductor_config.envoy_grpc_port,
                container_name=conductor_config.envoy_container_name,
            ))
            await _envoy_manager.init()
            _sandbox_controller._envoy_manager = _envoy_manager
            if hasattr(_sandbox_provider, '_envoy_manager'):
                _sandbox_provider._envoy_manager = _envoy_manager
            logger.info("   ✓ EnvoyManager initialized")
        except Exception as e:
            logger.warning("   ⚠️  EnvoyManager initialization failed: %s", e)
            _envoy_manager = None
    else:
        logger.info("   Envoy network isolation disabled")

    # Image builder
    if conductor_config.image_builder_enabled:
        try:
            from app.conductor.sandbox.image_builder import ImageBuilder
            _image_builder = ImageBuilder(
                default_base=conductor_config.image_builder_base,
            )
            logger.info("   ✓ ImageBuilder initialized")
        except Exception as e:
            logger.warning("   ⚠️  ImageBuilder initialization failed: %s", e)
    else:
        logger.info("   Image builder disabled")

    from app.conductor.kernel.runtime_config import RuntimeConfig

    _runtime_config = RuntimeConfig(
        idle_timeout_sec=conductor_config.sandbox_idle_timeout,
        stopped_max_age_sec=conductor_config.sandbox_stopped_ttl,
        heartbeat_timeout_sec=conductor_config.heartbeat_ttl,
        sandbox_failure_threshold=conductor_config.sandbox_failure_threshold,
        pool_min_size=conductor_config.sandbox_pool_min_size,
        pool_max_age_sec=conductor_config.sandbox_pool_max_age,
        event_batch_max_size=conductor_config.event_batch_max_size,
        event_batch_max_delay_ms=conductor_config.event_batch_max_delay_ms,
    )

    _setup_sighup_handler(_runtime_config, conductor_config)

    _adapter_registry = await AdapterRegistry.discover()
    logger.info("Discovered adapters: %s", _adapter_registry.provider_names())

    # Vault provider (encryption layer for credential storage)
    if conductor_config.vault_encryption_key:
        from app.conductor.services.vault_cipher import VaultCipher

        _vault_provider = VaultCipher(conductor_config.vault_encryption_key)
        logger.info("   ✓ VaultCipher initialized (encryption %s)",
                     "enabled" if _vault_provider.is_enabled else "passthrough")
    else:
        logger.info("   Vault encryption key not configured, vault provider disabled")

    # gRPC server for runner connections
    try:
        from app.conductor.grpc.server import start_grpc_server

        _grpc_server, _grpc_servicer = await start_grpc_server(
            bridge_registry=_bridge_registry,
            event_buffer=_event_buffer,
            queue=queue,
            host=conductor_config.grpc_host,
            port=conductor_config.grpc_port,
            vault_provider=_vault_provider,
        )
    except Exception as e:
        logger.warning("Failed to start gRPC server: %s", e)

    await _task_controller.recover_on_startup()

    _background_tasks.append(
        asyncio.create_task(_scheduler.run(), name="conductor-scheduler")
    )
    _background_tasks.append(
        asyncio.create_task(_task_controller.run(), name="conductor-task-ctrl")
    )
    _background_tasks.append(
        asyncio.create_task(
            _sandbox_controller.run_idle_sweep(), name="conductor-sandbox-sweep"
        )
    )
    _background_tasks.append(
        asyncio.create_task(
            _sandbox_controller.run_provisioning_poll(), name="conductor-prov-poll"
        )
    )
    _background_tasks.append(
        asyncio.create_task(
            _sandbox_controller.run_pool_manager(), name="conductor-pool-mgr"
        )
    )

    # HA: cross-instance command listener
    if _redis_coordinator and redis_client:
        from app.conductor.kernel.command_listener import CommandListener

        cmd_listener = CommandListener(redis_client, _redis_coordinator, _bridge_registry)
        _background_tasks.append(
            asyncio.create_task(cmd_listener.run(), name="conductor-cmd-listener")
        )

    logger.info("Conductor kernel started (%d background tasks)", len(_background_tasks))


async def conductor_shutdown() -> None:
    if not conductor_config.enabled:
        return

    logger.info("Shutting down Conductor kernel...")

    # Notify all active sandbox bridges to cancel in-flight processes
    if _bridge_registry:
        for bridge in _bridge_registry.all_bridges():
            try:
                bridge.request_cancel()
            except Exception:
                pass
        logger.info("Notified %d sandbox bridges to shut down", _bridge_registry.count())

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

    for task in _background_tasks:
        task.cancel()

    if _background_tasks:
        await asyncio.gather(*_background_tasks, return_exceptions=True)
    _background_tasks.clear()

    logger.info("Conductor kernel shut down")
