"""Redis command relay helpers for API-to-orchestrator runtime control."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.common.async_boundaries import async_boundary_error_payload

logger = logging.getLogger(__name__)

COMMAND_ACK_TIMEOUT_SECONDS = 2


async def publish_command_and_wait_for_ack(
    redis_client,
    channel: str,
    command: dict[str, Any],
    *,
    command_id: str,
    ack_key: str,
    boundary: str = "runtime_command",
    failure_code: str = "RUNTIME_REDIS_COMMAND_ACK_WAIT_FAILED",
    failure_message: str = "Redis command ACK wait failed",
    data: dict[str, Any] | None = None,
) -> bool:
    receivers = await redis_client.publish(channel, json.dumps(command))
    if receivers is None or int(receivers) == 0:
        return False

    try:
        ack = await redis_client.blpop(ack_key, timeout=COMMAND_ACK_TIMEOUT_SECONDS)
    except Exception as exc:
        logger.debug(
            "Redis command ACK wait failed for %s",
            command_id,
            extra={
                "error": async_boundary_error_payload(
                    code=failure_code,
                    message=failure_message,
                    boundary=boundary,
                    operation="wait_command_ack",
                    data={
                        "command_id": command_id,
                        "ack_key": ack_key,
                        "channel": channel,
                        **(data or {}),
                    },
                    detail=exc.__class__.__name__,
                )
            },
            exc_info=True,
        )
        return False
    if not ack:
        logger.debug("Redis command ACK timed out for %s", command_id)
        return False

    _key, raw_payload = ack
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode()
    try:
        payload = json.loads(raw_payload)
    except Exception:
        logger.debug("Redis command ACK payload is invalid for %s: %r", command_id, raw_payload)
        return False
    if str(payload.get("command_id") or "") != command_id:
        logger.debug("Redis command ACK command_id mismatch for %s: %s", command_id, payload)
        return False
    return bool(payload.get("ok"))


async def relay_sandbox_command_via_redis(
    sandbox_id,
    *,
    command_type: str,
    boundary: str,
    operation: str,
    failure_code: str,
    failure_message: str,
    reason: str | None = None,
    data: dict[str, Any] | None = None,
    extra_command: dict[str, Any] | None = None,
) -> bool:
    redis_client = RedisClient.get_client()
    if redis_client is None:
        return False

    sandbox_id_str = str(sandbox_id)
    try:
        owner = await redis_client.get(f"joysafeter:sandbox_owner:{sandbox_id_str}")
    except Exception:
        return False
    if not owner:
        return False
    if isinstance(owner, bytes):
        owner = owner.decode()

    command_id = uuid.uuid4().hex
    ack_key = f"joysafeter:cmd_ack:{command_id}"
    channel = f"joysafeter:cmd:{owner}"
    command: dict[str, Any] = {
        "type": command_type,
        "sandbox_id": sandbox_id_str,
        "command_id": command_id,
        "ack_key": ack_key,
    }
    if reason is not None:
        command["reason"] = reason
    if extra_command:
        command.update(extra_command)

    return await publish_command_and_wait_for_ack(
        redis_client,
        channel,
        command,
        command_id=command_id,
        ack_key=ack_key,
        boundary=boundary,
        failure_code=failure_code,
        failure_message=failure_message,
        data={
            "sandbox_id": sandbox_id_str,
            "command_type": command_type,
            "relay_operation": operation,
            **(data or {}),
        },
    )
