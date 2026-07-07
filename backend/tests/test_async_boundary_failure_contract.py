import asyncio
import json
import logging
import uuid

import pytest

from app.joysafeter_domain.services.joysafeter_session_service import publish_session_event_realtime
from app.joysafeter_orchestrator import lifespan as lifespan_module
from app.joysafeter_orchestrator.grpc.server import _best_effort_redis
from app.joysafeter_orchestrator.kernel import harness_input_builder as hib
from app.joysafeter_orchestrator.kernel import memory_sync as memory_sync_module
from app.joysafeter_orchestrator.kernel import scheduler as scheduler_module
from app.joysafeter_orchestrator.kernel import task_runner as task_runner_module
from app.joysafeter_orchestrator.kernel.command_listener import CommandListener
from app.joysafeter_orchestrator.kernel.queue import InMemoryRedisQueueBackend
from app.joysafeter_orchestrator.kernel.redis_coordinator import RedisCoordinator
from app.joysafeter_orchestrator.kernel.sandbox_controller import SandboxController
from app.joysafeter_orchestrator.kernel.sandbox_resolver import SandboxResolver
from app.joysafeter_orchestrator.kernel.scheduler import TaskScheduler
from app.joysafeter_orchestrator.kernel.task_controller import TaskController
from app.joysafeter_orchestrator.sandbox import file_injection as fi
from app.joysafeter_orchestrator.sandbox.docker_provider import DockerSandboxProvider
from app.joysafeter_orchestrator.sandbox.envoy_manager import EnvoyConfig, EnvoyManager
from app.joysafeter_orchestrator.sandbox.image_builder import ImageBuilder
from app.joysafeter_orchestrator.session_broadcaster import SessionBroadcaster
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload
from app.joysafeter_shared.common.boundary_errors import log_boundary_failure, log_boundary_failure_loguru
from app.joysafeter_shared.common.stream_errors import error_event, error_payload


class _FailingPublishRedis:
    async def publish(self, channel: str, payload: str) -> None:
        raise RuntimeError("redis down")


class _FailingAckRedis:
    async def rpush(self, key: str, payload: str) -> None:
        raise RuntimeError("ack redis down")

    async def expire(self, key: str, ttl: int) -> None:
        return None


class _FailingDeleteRedis:
    async def delete(self, key: str) -> None:
        raise RuntimeError("redis delete down")


class _FailingPopCoordinator:
    async def pop_from_global_queue(self, timeout_secs: float):
        raise RuntimeError("redis pop down")


class _FailingSandboxPopCoordinator:
    async def pop_from_sandbox_queue(self, sandbox_id: uuid.UUID, timeout_secs: float):
        raise RuntimeError("sandbox pop down")


async def _failing_redis_operation() -> None:
    raise RuntimeError("redis coordinator down")


class _FailingBridge:
    async def send_control_input(self, content: str) -> None:
        raise RuntimeError("bridge input down")


class _SuccessfulBridge:
    async def send_control_input(self, content: str) -> None:
        return None


class _FakeBridgeRegistry:
    async def get(self, sandbox_id: uuid.UUID):
        return _FailingBridge()


class _SuccessfulBridgeRegistry:
    async def get(self, sandbox_id: uuid.UUID):
        return _SuccessfulBridge()


class _MissingBridgeRegistry:
    async def get(self, sandbox_id: uuid.UUID):
        return None


class _FailingWatchdogController(TaskController):
    async def _check_overdue_tasks(self) -> None:
        raise RuntimeError("overdue down")

    async def _check_stuck_scheduling(self) -> None:
        raise RuntimeError("stuck down")

    async def _scan_pending_tasks(self) -> None:
        raise RuntimeError("pending down")


class _FailingLeaseController(TaskController):
    async def _renew_own_leases(self) -> None:
        raise RuntimeError("renew down")

    async def _reclaim_expired_leases(self) -> None:
        raise RuntimeError("reclaim down")


class _FailingWakeupQueue:
    async def pop_from_global(self):
        raise RuntimeError("wakeup down")


class _FailingSessionService:
    async def update_session_status_for_task_event(self, *args, **kwargs):
        raise RuntimeError("session idle down")


class _FakeLoguruLogger:
    def __init__(self):
        self.bound: dict | None = None
        self.messages: list[str] = []

    def bind(self, **kwargs):
        self.bound = kwargs
        return self

    def opt(self, **kwargs):
        return self

    def warning(self, message: str):
        self.messages.append(message)


class _FailingVaultCipher:
    def decrypt_or_passthrough(self, value: str) -> str:
        raise RuntimeError("cipher down")


class _FailingInjectionStrategy:
    name = "failing_strategy"

    async def inject(self, ctx, files):
        raise RuntimeError("injection down")


class _FakeStorage:
    pass


class _FailingListProvider:
    async def list_active(self):
        raise RuntimeError("provider list down")


class _FailingStartProvider:
    async def start(self, external_id: str) -> None:
        raise RuntimeError("provider start down")


class _FakeSandbox:
    def __init__(self, sandbox_id: uuid.UUID, external_id: str):
        self.id = sandbox_id
        self.external_id = external_id


class _FakeSandboxService:
    def __init__(self):
        self.marked_destroyed: list[uuid.UUID] = []

    async def update_status_and_config(self, *args, **kwargs):
        return None

    async def touch(self, sandbox_id: uuid.UUID):
        return None

    async def mark_destroyed(self, sandbox_id: uuid.UUID):
        self.marked_destroyed.append(sandbox_id)


class _FailingSweepSandboxController(SandboxController):
    async def _health_check_bridges(self) -> None:
        raise RuntimeError("health down")

    async def _expire_idle_sandboxes(self) -> None:
        raise RuntimeError("idle down")

    async def _force_stop_stuck(self) -> None:
        raise RuntimeError("force stop down")

    async def _destroy_stopped_sandboxes(self) -> None:
        raise RuntimeError("destroy down")

    async def cleanup_orphaned_provider_sandboxes(self) -> int:
        raise RuntimeError("orphan down")


def test_async_boundary_error_payload_uses_shared_error_contract():
    payload = async_boundary_error_payload(
        code="BOUNDARY_FAILED",
        message="Boundary failed",
        boundary="test_boundary",
        operation="publish",
        data={"resource_id": "res-1"},
        detail="RuntimeError",
    )

    assert payload == {
        "type": "error",
        "code": "BOUNDARY_FAILED",
        "message": "Boundary failed",
        "data": {
            "boundary": "test_boundary",
            "operation": "publish",
            "resource_id": "res-1",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_error_payload_normalizes_exceptions_through_app_error_contract():
    payload = error_payload(
        RuntimeError("redis down"),
        default_code="REDIS_PUBLISH_FAILED",
        default_message="Failed to publish event",
        data={"channel": "session.events"},
        source="runtime",
        retryable=True,
    )

    assert payload == {
        "type": "error",
        "code": "REDIS_PUBLISH_FAILED",
        "message": "Failed to publish event",
        "data": {"channel": "session.events", "detail": "redis down"},
        "source": "runtime",
        "retryable": True,
    }


def test_error_event_serializes_app_errors_with_stream_shape():
    event = error_event(
        InvalidRequestError(
            code="SESSION_RESOURCE_BODY_INVALID",
            message="Request body must be an object",
            data={"expected": "object"},
            user_action="fix_input",
        ),
        status=400,
    )

    prefix = "event: error\ndata: "
    assert event.startswith(prefix)
    assert event.endswith("\n\n")
    assert json.loads(event[len(prefix) : -2]) == {
        "type": "error",
        "code": "SESSION_RESOURCE_BODY_INVALID",
        "message": "Request body must be an object",
        "data": {"expected": "object"},
        "source": "api",
        "retryable": False,
        "user_action": "fix_input",
        "status": 400,
    }


def test_lifecycle_failure_logs_structured_boundary_error(caplog):
    with caplog.at_level(logging.WARNING):
        lifespan_module._log_lifecycle_boundary_failure(
            code="ORCHESTRATOR_GRPC_SERVER_START_FAILED",
            message="Failed to start gRPC server",
            operation="start_grpc_server",
            error=RuntimeError("grpc down"),
            data={"host": "127.0.0.1", "port": 50051},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "ORCHESTRATOR_GRPC_SERVER_START_FAILED",
        "message": "Failed to start gRPC server",
        "data": {
            "boundary": "orchestrator_lifecycle",
            "operation": "start_grpc_server",
            "host": "127.0.0.1",
            "port": 50051,
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_sandbox_provider_helper_logs_structured_boundary_error(caplog):
    provider_logger = logging.getLogger("tests.provider")

    with caplog.at_level(logging.WARNING):
        log_boundary_failure(
            provider_logger,
            boundary="docker_provider",
            code="DOCKER_STATUS_FAILED",
            message="Failed to read Docker container status",
            operation="status_container",
            error=RuntimeError("docker down"),
            data={"external_id": "joysafeter-sb"},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "DOCKER_STATUS_FAILED",
        "message": "Failed to read Docker container status",
        "data": {
            "boundary": "docker_provider",
            "operation": "status_container",
            "external_id": "joysafeter-sb",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_api_cleanup_failure_logs_structured_boundary_error(caplog):
    api_logger = logging.getLogger("tests.api")

    with caplog.at_level(logging.WARNING):
        log_boundary_failure(
            api_logger,
            boundary="session_api",
            code="SESSION_DELETE_GRPC_SHUTDOWN_FAILED",
            message="Failed to send gRPC Shutdown during session delete",
            operation="delete_session_shutdown_runner",
            error=RuntimeError("bridge down"),
            data={"session_id": "session-1", "sandbox_id": "sandbox-1"},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "SESSION_DELETE_GRPC_SHUTDOWN_FAILED",
        "message": "Failed to send gRPC Shutdown during session delete",
        "data": {
            "boundary": "session_api",
            "operation": "delete_session_shutdown_runner",
            "session_id": "session-1",
            "sandbox_id": "sandbox-1",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_api_loguru_failure_logs_structured_boundary_error():
    fake_logger = _FakeLoguruLogger()

    log_boundary_failure_loguru(
        fake_logger,
        boundary="websocket_auth",
        code="WEBSOCKET_REJECTION_FAILED",
        message="WebSocket rejection failed",
        operation="reject_websocket",
        error=RuntimeError("close down"),
        data={"close_code": 4001},
    )

    assert fake_logger.messages == ["WebSocket rejection failed"]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "WEBSOCKET_REJECTION_FAILED",
            "message": "WebSocket rejection failed",
            "data": {
                "boundary": "websocket_auth",
                "operation": "reject_websocket",
                "close_code": 4001,
            },
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


def test_task_runner_failure_logs_structured_boundary_error(caplog):
    task_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()

    with caplog.at_level(logging.WARNING):
        task_runner_module._log_task_runner_boundary_failure(
            code="TASK_RUNNER_EXECUTION_FAILED",
            message="Task execution failed in runner",
            operation="execute_task",
            error=RuntimeError("adapter down"),
            data={"task_id": str(task_id), "sandbox_id": str(sandbox_id)},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "TASK_RUNNER_EXECUTION_FAILED",
        "message": "Task execution failed in runner",
        "data": {
            "boundary": "task_runner",
            "operation": "execute_task",
            "task_id": str(task_id),
            "sandbox_id": str(sandbox_id),
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_memory_sync_failure_logs_structured_boundary_error(caplog):
    store_id = uuid.uuid4()
    session_id = uuid.uuid4()
    sandbox_id = uuid.uuid4()

    with caplog.at_level(logging.WARNING):
        memory_sync_module._log_memory_boundary_failure(
            code="MEMORY_SYNC_PEER_PUSH_FAILED",
            message="Failed to push MemoryFileUpdate to peer",
            operation="push_memory_update",
            error=RuntimeError("bridge down"),
            data={
                "store_id": str(store_id),
                "session_id": str(session_id),
                "sandbox_id": str(sandbox_id),
                "mount_name": "docs",
                "relative_path": "readme.md",
            },
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "MEMORY_SYNC_PEER_PUSH_FAILED",
        "message": "Failed to push MemoryFileUpdate to peer",
        "data": {
            "boundary": "memory_sync",
            "operation": "push_memory_update",
            "store_id": str(store_id),
            "session_id": str(session_id),
            "sandbox_id": str(sandbox_id),
            "mount_name": "docs",
            "relative_path": "readme.md",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_runtime_failure_logs_structured_boundary_error(caplog):
    runtime_logger = logging.getLogger("tests.runtime")

    with caplog.at_level(logging.WARNING):
        log_boundary_failure(
            runtime_logger,
            boundary="claude_settings",
            code="CLAUDE_SETTINGS_WRITE_FAILED",
            message="Failed to write Claude settings",
            operation="write_claude_settings",
            error=OSError("disk full"),
            data={"path": "/workspace/.claude/settings.json"},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "CLAUDE_SETTINGS_WRITE_FAILED",
        "message": "Failed to write Claude settings",
        "data": {
            "boundary": "claude_settings",
            "operation": "write_claude_settings",
            "path": "/workspace/.claude/settings.json",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "OSError",
    }


def test_domain_failure_logs_structured_boundary_error(caplog):
    domain_logger = logging.getLogger("tests.domain")

    with caplog.at_level(logging.WARNING):
        log_boundary_failure(
            domain_logger,
            boundary="vault_cipher",
            code="VAULT_DECRYPTION_FAILED",
            message="Vault decryption failed",
            operation="decrypt_credential",
            error=RuntimeError("cipher down"),
            retryable=False,
            user_action="check_configuration",
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "VAULT_DECRYPTION_FAILED",
        "message": "Vault decryption failed",
        "data": {
            "boundary": "vault_cipher",
            "operation": "decrypt_credential",
        },
        "source": "runtime",
        "retryable": False,
        "user_action": "check_configuration",
        "detail": "RuntimeError",
    }


def test_domain_loguru_failure_logs_structured_boundary_error():
    fake_logger = _FakeLoguruLogger()

    log_boundary_failure_loguru(
        fake_logger,
        boundary="email_service",
        code="EMAIL_SEND_FAILED",
        message="Failed to send email",
        operation="send_email",
        error=RuntimeError("smtp down"),
        data={"smtp_host": "smtp.example.test", "smtp_port": 587},
    )

    assert fake_logger.messages == ["Failed to send email"]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "EMAIL_SEND_FAILED",
            "message": "Failed to send email",
            "data": {
                "boundary": "email_service",
                "operation": "send_email",
                "smtp_host": "smtp.example.test",
                "smtp_port": 587,
            },
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_docker_limited_networking_without_envoy_logs_structured_boundary_error(caplog):
    provider = object.__new__(DockerSandboxProvider)
    provider._envoy_manager = None
    sandbox_id = uuid.uuid4()

    with caplog.at_level(logging.WARNING):
        await provider.setup_networking(sandbox_id, {"type": "limited"})

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "DOCKER_LIMITED_NETWORKING_ENVOY_MISSING",
        "message": "Limited networking requested without Envoy manager",
        "data": {
            "boundary": "docker_provider",
            "operation": "setup_networking",
            "sandbox_id": str(sandbox_id),
        },
        "source": "runtime",
        "retryable": False,
        "user_action": "check_configuration",
    }


def test_envoy_invalid_sandbox_entry_logs_structured_boundary_error(caplog, tmp_path):
    sandboxes_dir = tmp_path / "sandboxes"
    sandboxes_dir.mkdir()
    bad_entry = sandboxes_dir / "bad.json"
    bad_entry.write_text("{not json")
    manager = EnvoyManager(EnvoyConfig(config_dir=str(tmp_path)))

    with caplog.at_level(logging.WARNING):
        result = manager._load_sandboxes_from_disk()

    assert result == {}
    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "ENVOY_SANDBOX_ENTRY_PARSE_FAILED",
        "message": "Failed to parse Envoy sandbox entry",
        "data": {
            "boundary": "envoy_manager",
            "operation": "load_sandbox_entry",
            "entry_path": str(bad_entry),
        },
        "source": "runtime",
        "retryable": False,
        "user_action": "check_configuration",
        "detail": "JSONDecodeError",
    }


def test_image_builder_unsafe_package_logs_structured_boundary_error(caplog):
    with caplog.at_level(logging.WARNING):
        result = ImageBuilder._sanitize_packages(["requests", "../bad"])

    assert result == ["requests"]
    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "IMAGE_BUILDER_UNSAFE_PACKAGE_REJECTED",
        "message": "Rejected unsafe package name",
        "data": {
            "boundary": "image_builder",
            "operation": "sanitize_packages",
            "package": "../bad",
        },
        "source": "runtime",
        "retryable": False,
        "user_action": "correct_request",
    }


@pytest.mark.asyncio
async def test_scheduler_wakeup_wait_failure_logs_structured_boundary_error(monkeypatch):
    fake_logger = _FakeLoguruLogger()
    monkeypatch.setattr(scheduler_module, "logger", fake_logger)
    scheduler = TaskScheduler(_FailingWakeupQueue())

    try:
        await scheduler._queue.pop_from_global()
    except Exception as exc:
        scheduler._log_boundary_failure(
            code="SCHEDULER_WAKEUP_WAIT_FAILED",
            message="Scheduler wakeup wait failed",
            operation="wait_for_global_wakeup",
            error=exc,
        )

    assert fake_logger.messages == ["Scheduler wakeup wait failed"]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "SCHEDULER_WAKEUP_WAIT_FAILED",
            "message": "Scheduler wakeup wait failed",
            "data": {
                "boundary": "scheduler",
                "operation": "wait_for_global_wakeup",
            },
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_scheduler_idle_transition_failure_logs_structured_boundary_error(monkeypatch):
    fake_logger = _FakeLoguruLogger()
    monkeypatch.setattr(scheduler_module, "logger", fake_logger)
    task_id = uuid.uuid4()
    session_id = uuid.uuid4()

    await TaskScheduler._idle_task_session(
        _FailingSessionService(),
        task_id,
        session_id,
        {"type": "cancelled"},
    )

    assert fake_logger.messages == ["Could not transition session to idle for terminal task"]
    assert fake_logger.bound == {
        "error": {
            "type": "error",
            "code": "SCHEDULER_SESSION_IDLE_TRANSITION_FAILED",
            "message": "Could not transition session to idle for terminal task",
            "data": {
                "boundary": "scheduler",
                "operation": "idle_task_session",
                "session_id": str(session_id),
                "task_id": str(task_id),
            },
            "source": "runtime",
            "retryable": True,
            "user_action": "retry",
            "detail": "RuntimeError",
        }
    }


@pytest.mark.asyncio
async def test_file_injection_strategy_failure_logs_structured_boundary_errors(caplog, monkeypatch):
    session_id = uuid.uuid4()

    async def fake_load_session_files(_session_id):
        return [
            fi.SessionFileRecord(
                mount_path="/workspace/file.txt",
                storage_key="storage-key-1",
                filename="file.txt",
                size_bytes=12,
            )
        ]

    monkeypatch.setattr(fi, "load_session_files", fake_load_session_files)
    monkeypatch.setattr(fi, "select_strategies", lambda _ctx: [_FailingInjectionStrategy()])
    ctx = fi.FileInjectionContext(
        session_id=session_id,
        external_id="ext-1",
        workspace_path=None,
        provider=object(),
        storage=_FakeStorage(),
    )

    with caplog.at_level(logging.WARNING):
        await fi.inject_session_files(ctx)

    errors = [record.error for record in caplog.records]
    assert [error["code"] for error in errors] == [
        "FILE_INJECTION_STRATEGY_FAILED",
        "FILE_INJECTION_ALL_STRATEGIES_FAILED",
    ]
    assert errors[0]["data"] == {
        "boundary": "file_injection",
        "operation": "run_injection_strategy",
        "session_id": str(session_id),
        "strategy": "failing_strategy",
    }
    assert errors[0]["detail"] == "RuntimeError"
    assert errors[1]["data"] == {
        "boundary": "file_injection",
        "operation": "inject_session_files",
        "session_id": str(session_id),
        "file_count": 1,
    }


@pytest.mark.asyncio
async def test_harness_oauth_refresh_failure_logs_structured_boundary_error_without_secret(caplog):
    credential = {
        "id": "cred-1",
        "credential_type": "oauth",
        "token_value": "old-access-token",
        "oauth_config": {
            "expires_at": 0,
            "token_url": "file:///etc/passwd",
            "refresh_token": "secret-refresh-token",
            "client_id": "client-1",
            "client_secret": "secret-client-secret",
        },
    }

    with caplog.at_level(logging.WARNING):
        result = await hib._maybe_refresh_oauth(credential, db_session=None)

    assert result is credential
    assert len(caplog.records) == 1
    error = caplog.records[0].error
    assert error["code"] == "HARNESS_OAUTH_REFRESH_FAILED"
    assert error["data"] == {
        "boundary": "harness_input_builder",
        "operation": "refresh_oauth_credential",
        "credential_id": "cred-1",
    }
    assert "secret-refresh-token" not in str(error)
    assert "secret-client-secret" not in str(error)


def test_harness_vault_decrypt_failure_logs_structured_boundary_error(caplog, monkeypatch):
    monkeypatch.setattr(hib, "_vault_cipher", _FailingVaultCipher())

    with caplog.at_level(logging.WARNING):
        result = hib._decrypt_credential_value("enc:secret")

    assert result == "enc:secret"
    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "HARNESS_VAULT_CREDENTIAL_DECRYPT_FAILED",
        "message": "VaultCipher credential decryption failed",
        "data": {
            "boundary": "harness_input_builder",
            "operation": "decrypt_credential_value",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_sandbox_controller_provider_orphan_scan_failure_logs_structured_boundary_error(caplog):
    controller = SandboxController(
        queue=object(),
        bridge_registry=object(),
        provider=_FailingListProvider(),
    )

    with caplog.at_level(logging.WARNING):
        result = await controller.cleanup_orphaned_provider_sandboxes()

    assert result == 0
    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "SANDBOX_PROVIDER_ORPHAN_SCAN_FAILED",
        "message": "Provider orphan sandbox scan failed",
        "data": {
            "boundary": "sandbox_controller",
            "operation": "provider_orphan_scan",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_sandbox_controller_idle_sweep_iteration_logs_structured_boundary_errors(caplog):
    controller = _FailingSweepSandboxController(
        queue=object(),
        bridge_registry=object(),
        provider=object(),
    )

    with caplog.at_level(logging.WARNING):
        await controller._run_idle_sweep_iteration(orphan_cleanup_counter=10)

    errors = [record.error for record in caplog.records]
    assert [error["code"] for error in errors] == [
        "SANDBOX_HEALTH_CHECK_FAILED",
        "SANDBOX_IDLE_REAP_FAILED",
        "SANDBOX_STUCK_STOPPING_FAILED",
        "SANDBOX_DESTROY_STOPPED_FAILED",
        "SANDBOX_PERIODIC_ORPHAN_CLEANUP_FAILED",
    ]
    assert {error["data"]["boundary"] for error in errors} == {"sandbox_controller"}
    assert [error["data"]["operation"] for error in errors] == [
        "health_check_bridges",
        "expire_idle_sandboxes",
        "force_stop_stuck",
        "destroy_stopped_sandboxes",
        "periodic_orphan_cleanup",
    ]
    assert {error["detail"] for error in errors} == {"RuntimeError"}


@pytest.mark.asyncio
async def test_sandbox_resolver_restart_failure_logs_structured_boundary_error(caplog):
    sandbox_id = uuid.uuid4()
    resolver = SandboxResolver(provider=_FailingStartProvider())
    svc = _FakeSandboxService()

    with caplog.at_level(logging.WARNING):
        result = await resolver._restart_sandbox(svc, _FakeSandbox(sandbox_id, "ext-1"))

    assert result is False
    assert svc.marked_destroyed == [sandbox_id]
    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "SANDBOX_RESOLVER_RESTART_FAILED",
        "message": "Failed to restart stopped sandbox",
        "data": {
            "boundary": "sandbox_resolver",
            "operation": "restart_stopped_sandbox",
            "sandbox_id": str(sandbox_id),
            "external_id": "ext-1",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_task_controller_watchdog_iteration_logs_structured_boundary_errors(caplog):
    controller = _FailingWatchdogController(queue=object())

    with caplog.at_level(logging.WARNING):
        await controller._run_watchdog_iteration()

    errors = [record.error for record in caplog.records]
    assert [error["code"] for error in errors] == [
        "TASK_CONTROLLER_OVERDUE_CHECK_FAILED",
        "TASK_CONTROLLER_STUCK_SCHEDULING_CHECK_FAILED",
        "TASK_CONTROLLER_PENDING_SCAN_FAILED",
    ]
    assert {error["data"]["boundary"] for error in errors} == {"task_controller"}
    assert [error["data"]["operation"] for error in errors] == [
        "check_overdue_tasks",
        "check_stuck_scheduling",
        "scan_pending_tasks",
    ]
    assert {error["detail"] for error in errors} == {"RuntimeError"}


@pytest.mark.asyncio
async def test_task_controller_lease_iteration_logs_structured_boundary_errors(caplog):
    controller = _FailingLeaseController(queue=object())

    with caplog.at_level(logging.WARNING):
        await controller._run_lease_iteration()

    errors = [record.error for record in caplog.records]
    assert [error["code"] for error in errors] == [
        "TASK_CONTROLLER_LEASE_RENEWAL_FAILED",
        "TASK_CONTROLLER_LEASE_RECLAIM_FAILED",
    ]
    assert {error["data"]["boundary"] for error in errors} == {"task_controller"}
    assert [error["data"]["operation"] for error in errors] == [
        "renew_own_leases",
        "reclaim_expired_leases",
    ]
    assert {error["detail"] for error in errors} == {"RuntimeError"}


@pytest.mark.asyncio
async def test_grpc_best_effort_redis_failure_logs_structured_boundary_error(caplog):
    with caplog.at_level(logging.WARNING):
        await _best_effort_redis("publish_event", _failing_redis_operation())

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "GRPC_REDIS_COORDINATOR_FAILED",
        "message": "Redis coordinator operation failed",
        "data": {
            "boundary": "grpc_agent_bridge",
            "operation": "publish_event",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_command_listener_dispatch_failure_logs_structured_boundary_error(caplog):
    sandbox_id = uuid.uuid4()
    listener = CommandListener(
        redis_client=None,
        coordinator=object(),
        bridge_registry=_FakeBridgeRegistry(),
    )

    with caplog.at_level(logging.WARNING):
        await listener._dispatch({"type": "input", "sandbox_id": str(sandbox_id), "content": "approve"})

    errors = [getattr(record, "error", None) for record in caplog.records if getattr(record, "error", None)]
    assert len(errors) == 1
    assert errors[0] == {
        "type": "error",
        "code": "COMMAND_LISTENER_DISPATCH_FAILED",
        "message": "Command listener failed to dispatch command",
        "data": {
            "boundary": "command_listener",
            "operation": "dispatch_command",
            "command_id": "",
            "command_type": "input",
            "sandbox_id": str(sandbox_id),
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_command_listener_missing_bridge_logs_structured_boundary_error(caplog):
    sandbox_id = uuid.uuid4()
    listener = CommandListener(
        redis_client=None,
        coordinator=object(),
        bridge_registry=_MissingBridgeRegistry(),
    )

    with caplog.at_level(logging.WARNING):
        result = await listener._dispatch_inner({"type": "input", "sandbox_id": str(sandbox_id), "content": "approve"})

    assert result is False
    errors = [getattr(record, "error", None) for record in caplog.records if getattr(record, "error", None)]
    assert len(errors) == 1
    assert errors[0]["code"] == "COMMAND_LISTENER_BRIDGE_NOT_FOUND"
    assert errors[0]["data"] == {
        "boundary": "command_listener",
        "operation": "resolve_bridge",
        "command_type": "input",
        "sandbox_id": str(sandbox_id),
    }


@pytest.mark.asyncio
async def test_command_listener_invalid_ack_key_logs_structured_boundary_error(caplog):
    sandbox_id = uuid.uuid4()
    listener = CommandListener(
        redis_client=object(),
        coordinator=object(),
        bridge_registry=_SuccessfulBridgeRegistry(),
    )

    with caplog.at_level(logging.WARNING):
        await listener._dispatch(
            {
                "type": "input",
                "sandbox_id": str(sandbox_id),
                "content": "approve",
                "command_id": "cmd-1",
                "ack_key": "attacker:list",
            }
        )

    errors = [getattr(record, "error", None) for record in caplog.records if getattr(record, "error", None)]
    assert len(errors) == 1
    assert errors[0]["code"] == "COMMAND_LISTENER_INVALID_ACK_KEY"
    assert errors[0]["retryable"] is False
    assert "user_action" not in errors[0]
    assert errors[0]["data"] == {
        "boundary": "command_listener",
        "operation": "validate_ack_key",
        "ack_key": "attacker:list",
        "command_id": "cmd-1",
        "command_type": "input",
        "sandbox_id": str(sandbox_id),
    }


@pytest.mark.asyncio
async def test_session_broadcaster_redis_publish_failure_logs_structured_boundary_error(caplog):
    session_id = uuid.uuid4()
    broadcaster = SessionBroadcaster(redis_client=_FailingPublishRedis(), instance_id="inst-1")
    channel = f"joysafeter:session_events:{session_id}"

    with caplog.at_level(logging.WARNING):
        await broadcaster._publish_to_redis(channel, "{}")

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "SESSION_BROADCAST_REDIS_PUBLISH_FAILED",
        "message": "Failed to publish session event to Redis",
        "data": {
            "boundary": "session_broadcaster",
            "operation": "redis_publish",
            "channel": channel,
            "session_id": str(session_id),
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_redis_coordinator_remove_sandbox_queue_failure_logs_structured_boundary_error(caplog):
    sandbox_id = uuid.uuid4()
    coordinator = RedisCoordinator(_FailingDeleteRedis(), instance_id="inst-1")

    with caplog.at_level(logging.WARNING):
        await coordinator.remove_sandbox_queue(sandbox_id)

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "REDIS_SANDBOX_QUEUE_REMOVE_FAILED",
        "message": "Failed to remove sandbox queue",
        "data": {
            "boundary": "redis_coordinator",
            "operation": "remove_sandbox_queue",
            "sandbox_id": str(sandbox_id),
            "key": f"joysafeter:sandbox_wakeup:{sandbox_id}",
            "instance_id": "inst-1",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_redis_coordinator_deregister_failure_logs_structured_boundary_error(caplog):
    coordinator = RedisCoordinator(_FailingDeleteRedis(), instance_id="inst-1")

    with caplog.at_level(logging.WARNING):
        await coordinator.deregister_instance()

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "REDIS_INSTANCE_DEREGISTER_FAILED",
        "message": "Failed to deregister instance",
        "data": {
            "boundary": "redis_coordinator",
            "operation": "deregister_instance",
            "instance_id": "inst-1",
            "key": "joysafeter:instances:inst-1",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_queue_global_pop_failure_logs_structured_boundary_error(caplog):
    task_id = uuid.uuid4()
    queue = InMemoryRedisQueueBackend(_FailingPopCoordinator())
    queue._global_queue.push(task_id)

    with caplog.at_level(logging.WARNING):
        result = await queue.pop_from_global()

    assert result == task_id
    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "QUEUE_GLOBAL_REDIS_POP_FAILED",
        "message": "Redis global queue pop failed; checking local queue",
        "data": {
            "boundary": "queue",
            "operation": "pop_from_global",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_queue_sandbox_wakeup_wait_failure_logs_structured_boundary_error(caplog):
    sandbox_id = uuid.uuid4()
    queue = InMemoryRedisQueueBackend(redis_coord=_FailingSandboxPopCoordinator())

    with caplog.at_level(logging.WARNING):
        await queue.wait_for_sandbox_wakeup(sandbox_id, asyncio.Event(), timeout_secs=1)

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "QUEUE_SANDBOX_WAKEUP_WAIT_FAILED",
        "message": "Sandbox wakeup wait failed",
        "data": {
            "boundary": "task_queue",
            "operation": "wait_for_sandbox_wakeup",
            "sandbox_id": str(sandbox_id),
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_command_ack_publish_failure_logs_structured_boundary_error(caplog):
    listener = CommandListener(
        redis_client=_FailingAckRedis(),
        coordinator=object(),
        bridge_registry=object(),
    )

    with caplog.at_level(logging.WARNING):
        await listener._ack_command(
            "joysafeter:cmd_ack:cmd-1",
            "cmd-1",
            success=False,
            error="dispatch failed",
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "COMMAND_ACK_PUBLISH_FAILED",
        "message": "Failed to publish command acknowledgement",
        "data": {
            "boundary": "command_listener",
            "operation": "publish_ack",
            "ack_key": "joysafeter:cmd_ack:cmd-1",
            "command_id": "cmd-1",
            "success": False,
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_redis_coordinator_task_event_publish_failure_logs_structured_boundary_error(caplog):
    task_id = uuid.uuid4()
    coordinator = RedisCoordinator(_FailingPublishRedis(), instance_id="inst-1")

    with caplog.at_level(logging.WARNING):
        await coordinator.publish_event(task_id, '{"type":"complete"}')

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "REDIS_TASK_EVENT_PUBLISH_FAILED",
        "message": "Failed to publish task event to Redis",
        "data": {
            "boundary": "redis_coordinator",
            "operation": "publish_task_event",
            "task_id": str(task_id),
            "channel": f"joysafeter:events:{task_id}",
            "instance_id": "inst-1",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_session_realtime_publish_failure_logs_structured_boundary_error(caplog, monkeypatch):
    session_id = uuid.uuid4()
    event_id = uuid.uuid4()
    monkeypatch.setattr(
        "app.joysafeter_shared.cache.redis.RedisClient.get_client",
        staticmethod(lambda: _FailingPublishRedis()),
    )

    with caplog.at_level(logging.WARNING):
        await publish_session_event_realtime(
            session_id=session_id,
            event_id=event_id,
            event_type="agent.message",
            seq=7,
            payload={"text": "hello"},
        )

    assert len(caplog.records) == 1
    assert caplog.records[0].error == {
        "type": "error",
        "code": "SESSION_REALTIME_REDIS_PUBLISH_FAILED",
        "message": "Failed to publish session event realtime",
        "data": {
            "boundary": "session_event_realtime",
            "operation": "redis_publish",
            "session_id": str(session_id),
            "event_id": str(event_id),
            "event_type": "agent.message",
            "seq": 7,
            "channel": f"joysafeter:session_events:{session_id}",
        },
        "source": "runtime",
        "retryable": True,
        "user_action": "retry",
        "detail": "RuntimeError",
    }


def test_boundary_payload_honors_explicit_error_class():
    from app.joysafeter_shared.common.app_errors import NotFoundError
    from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload

    payload = async_boundary_error_payload(
        code="TASK_AGENT_NOT_FOUND",
        message="agent gone",
        boundary="worker",
        operation="dispatch",
        error_class=NotFoundError,
    )
    assert payload["code"] == "TASK_AGENT_NOT_FOUND"
    # NotFoundError default retryable is False -- not the old hardcoded 503 retryable=True.
    assert payload["retryable"] is False


def test_boundary_payload_defaults_to_service_unavailable():
    from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload

    payload = async_boundary_error_payload(code="REDIS_DOWN", message="redis", boundary="bus", operation="publish")
    assert payload["retryable"] is True
