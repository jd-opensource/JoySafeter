"""Cross-instance command listener via Redis pub/sub.

Subscribes to `joysafeter:cmd:{instance_id}` and dispatches commands
to the appropriate sandbox bridge. Matches Rust's spawn_command_listener
+ handle_remote_command in grpc.rs.
"""

import asyncio
import json
import logging
import uuid
from typing import Any

from app.joysafeter_orchestrator.grpc.proto import joysafeter_pb2
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload

logger = logging.getLogger(__name__)
COMMAND_ACK_KEY_PREFIX = "joysafeter:cmd_ack:"


class CommandListener:
    def __init__(self, redis_client, coordinator, bridge_registry):
        self._redis = redis_client
        self._coordinator = coordinator
        self._bridge_registry = bridge_registry
        self._task: asyncio.Task | None = None

    async def run(self) -> None:
        channel = self._coordinator.command_channel()
        backoff = 1.0
        max_backoff = 30.0
        while True:
            pubsub = self._redis.pubsub()
            try:
                await pubsub.subscribe(channel)
                logger.info("Cross-instance command listener started on channel %s", channel)
                backoff = 1.0  # reset on successful connect
            except asyncio.CancelledError:
                await pubsub.close()
                return
            except Exception as e:
                logger.warning(
                    "Command listener: failed to connect to Redis pub/sub",
                    extra={
                        "error": async_boundary_error_payload(
                            code="COMMAND_LISTENER_REDIS_CONNECT_FAILED",
                            message="Command listener failed to connect to Redis pub/sub",
                            boundary="command_listener",
                            operation="connect_pubsub",
                            data={"channel": channel},
                            detail=e.__class__.__name__,
                        )
                    },
                    exc_info=True,
                )
                try:
                    await pubsub.close()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
                continue

            try:
                async for message in pubsub.listen():
                    if message["type"] != "message":
                        continue
                    try:
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode()
                        cmd = json.loads(data)
                        await self._dispatch(cmd)
                    except Exception as e:
                        logger.warning(
                            "Command listener: bad payload",
                            extra={
                                "error": async_boundary_error_payload(
                                    code="COMMAND_LISTENER_BAD_PAYLOAD",
                                    message="Command listener received an invalid payload",
                                    boundary="command_listener",
                                    operation="decode_command",
                                    data={"channel": channel},
                                    retryable=False,
                                    user_action=None,
                                    detail=e.__class__.__name__,
                                )
                            },
                            exc_info=True,
                        )
            except asyncio.CancelledError:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                return
            except Exception:
                pass

            try:
                await pubsub.unsubscribe(channel)
                await pubsub.close()
            except Exception:
                pass
            logger.warning("Command listener: stream ended, reconnecting in %.0fs...", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    async def _dispatch(self, cmd: dict) -> None:
        ack_key = cmd.get("ack_key")
        command_id = cmd.get("command_id")
        success = False
        error: str | None = None
        try:
            success = await self._dispatch_inner(cmd)
        except Exception as exc:
            error = str(exc)
            logger.warning(
                "Command listener: dispatch failed",
                extra={
                    "error": async_boundary_error_payload(
                        code="COMMAND_LISTENER_DISPATCH_FAILED",
                        message="Command listener failed to dispatch command",
                        boundary="command_listener",
                        operation="dispatch_command",
                        data={
                            "command_id": str(command_id or ""),
                            "command_type": str(cmd.get("type") or ""),
                            "sandbox_id": str(cmd.get("sandbox_id") or ""),
                        },
                        detail=exc.__class__.__name__,
                    )
                },
                exc_info=True,
            )
        if ack_key:
            ack_key_str = str(ack_key)
            if ack_key_str.startswith(COMMAND_ACK_KEY_PREFIX):
                await self._ack_command(ack_key_str, command_id, success=success, error=error)
            else:
                self._log_boundary_failure(
                    code="COMMAND_LISTENER_INVALID_ACK_KEY",
                    message="Command listener refused invalid ack key",
                    operation="validate_ack_key",
                    data={
                        "ack_key": ack_key_str,
                        "command_id": str(command_id or ""),
                        "command_type": str(cmd.get("type") or ""),
                        "sandbox_id": str(cmd.get("sandbox_id") or ""),
                    },
                    retryable=False,
                    user_action=None,
                )

    @staticmethod
    def _log_boundary_failure(
        *,
        code: str,
        message: str,
        operation: str,
        data: dict[str, object] | None = None,
        retryable: bool = True,
        user_action: str | None = "retry",
    ) -> None:
        logger.warning(
            message,
            extra={
                "error": async_boundary_error_payload(
                    code=code,
                    message=message,
                    boundary="command_listener",
                    operation=operation,
                    data=data,
                    retryable=retryable,
                    user_action=user_action,
                )
            },
        )

    async def _ack_command(
        self,
        ack_key: str,
        command_id: Any,
        *,
        success: bool,
        error: str | None = None,
    ) -> None:
        payload = {
            "command_id": str(command_id or ""),
            "ok": success,
        }
        if error:
            payload["error"] = error
        try:
            await self._redis.rpush(ack_key, json.dumps(payload))
            await self._redis.expire(ack_key, 30)
        except Exception as exc:
            logger.warning(
                "Command listener: failed to publish command ack",
                extra={
                    "error": async_boundary_error_payload(
                        code="COMMAND_ACK_PUBLISH_FAILED",
                        message="Failed to publish command acknowledgement",
                        boundary="command_listener",
                        operation="publish_ack",
                        data={
                            "ack_key": ack_key,
                            "command_id": str(command_id or ""),
                            "success": success,
                        },
                        detail=exc.__class__.__name__,
                    )
                },
                exc_info=True,
            )

    async def _dispatch_inner(self, cmd: dict) -> bool:
        sandbox_id_str = cmd.get("sandbox_id", "")
        if not sandbox_id_str:
            self._log_boundary_failure(
                code="COMMAND_LISTENER_INVALID_SANDBOX_ID",
                message="Command listener received command without sandbox id",
                operation="validate_command",
                data={"command_type": str(cmd.get("type") or ""), "sandbox_id": str(sandbox_id_str or "")},
                retryable=False,
                user_action=None,
            )
            return False

        try:
            sandbox_id = uuid.UUID(sandbox_id_str)
        except ValueError:
            self._log_boundary_failure(
                code="COMMAND_LISTENER_INVALID_SANDBOX_ID",
                message="Command listener received invalid sandbox id",
                operation="validate_command",
                data={"command_type": str(cmd.get("type") or ""), "sandbox_id": sandbox_id_str},
                retryable=False,
                user_action=None,
            )
            return False

        bridge = await self._bridge_registry.get(sandbox_id)
        if not bridge:
            self._log_boundary_failure(
                code="COMMAND_LISTENER_BRIDGE_NOT_FOUND",
                message="Command listener found no bridge for sandbox",
                operation="resolve_bridge",
                data={"command_type": str(cmd.get("type") or ""), "sandbox_id": str(sandbox_id)},
            )
            return False

        cmd_type = cmd.get("type", "")
        if cmd_type == "input":
            content = cmd.get("content", "")
            # Deliver on the channel the runner loops actually consume: the
            # bridge's _control_queue (drained by the gRPC task loop on
            # confirmation, and by the in-process TaskRunner control loop) plus
            # confirmation_event. The old runner_tx queue had no consumer, so
            # enqueuing there silently dropped remote input.
            await bridge.send_control_input(content)
            logger.info("Executed remote command: sandbox=%s type=input", sandbox_id)
            return True
        elif cmd_type == "cancel":
            # request_cancel() sets the _cancel_event that BOTH the gRPC task
            # loop and the in-process runner watch to write CancelTask to the
            # runner.
            bridge.request_cancel()
            logger.info("Executed remote command: sandbox=%s type=cancel", sandbox_id)
            return True
        elif cmd_type == "shutdown":
            reason = cmd.get("reason", "remote shutdown")
            msg = joysafeter_pb2.OrchestratorMessage(shutdown=joysafeter_pb2.Shutdown(reason=reason))
            written = await bridge.write_to_runner(msg)
            logger.info("Executed remote command: sandbox=%s type=shutdown", sandbox_id)
            return bool(written)
        else:
            self._log_boundary_failure(
                code="COMMAND_LISTENER_UNKNOWN_COMMAND",
                message="Command listener received unknown command type",
                operation="validate_command_type",
                data={"command_type": str(cmd_type or ""), "sandbox_id": str(sandbox_id)},
                retryable=False,
                user_action=None,
            )
            return False
