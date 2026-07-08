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
SANDBOX_DESTROY_ACK_TIMEOUT_SECONDS = 30
ENVIRONMENT_IMAGE_BUILD_ACK_TIMEOUT_SECONDS = 600
SANDBOX_DESTROY_BROADCAST_CHANNEL = "joysafeter:cmd:destroy"


async def publish_command_and_wait_for_ack_payload(
    redis_client,
    channel: str,
    command: dict[str, Any],
    *,
    command_id: str,
    ack_key: str,
    ack_timeout_seconds: int = COMMAND_ACK_TIMEOUT_SECONDS,
    boundary: str = "runtime_command",
    failure_code: str = "RUNTIME_REDIS_COMMAND_ACK_WAIT_FAILED",
    failure_message: str = "Redis command ACK wait failed",
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    receivers = await redis_client.publish(channel, json.dumps(command))
    if receivers is None or int(receivers) == 0:
        return None

    try:
        ack = await redis_client.blpop(ack_key, timeout=ack_timeout_seconds)
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
        return None
    if not ack:
        logger.debug("Redis command ACK timed out for %s", command_id)
        return None

    _key, raw_payload = ack
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode()
    try:
        payload = json.loads(raw_payload)
    except Exception:
        logger.debug("Redis command ACK payload is invalid for %s: %r", command_id, raw_payload)
        return None
    if str(payload.get("command_id") or "") != command_id:
        logger.debug("Redis command ACK command_id mismatch for %s: %s", command_id, payload)
        return None
    return payload


async def publish_command_and_wait_for_ack(
    redis_client,
    channel: str,
    command: dict[str, Any],
    *,
    command_id: str,
    ack_key: str,
    ack_timeout_seconds: int = COMMAND_ACK_TIMEOUT_SECONDS,
    boundary: str = "runtime_command",
    failure_code: str = "RUNTIME_REDIS_COMMAND_ACK_WAIT_FAILED",
    failure_message: str = "Redis command ACK wait failed",
    data: dict[str, Any] | None = None,
) -> bool:
    payload = await publish_command_and_wait_for_ack_payload(
        redis_client,
        channel,
        command,
        command_id=command_id,
        ack_key=ack_key,
        ack_timeout_seconds=ack_timeout_seconds,
        boundary=boundary,
        failure_code=failure_code,
        failure_message=failure_message,
        data=data,
    )
    if payload is None:
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
    ack_timeout_seconds: int = COMMAND_ACK_TIMEOUT_SECONDS,
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
        ack_timeout_seconds=ack_timeout_seconds,
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


async def relay_sandbox_destroy_via_redis(
    sandbox_id,
    *,
    boundary: str,
    operation: str,
    failure_code: str,
    failure_message: str,
    reason: str,
    external_id: str | None = None,
    data: dict[str, Any] | None = None,
) -> bool:
    redis_client = RedisClient.get_client()
    if redis_client is None:
        return False

    sandbox_id_str = str(sandbox_id)
    owner = None
    try:
        owner = await redis_client.get(f"joysafeter:sandbox_owner:{sandbox_id_str}")
    except Exception:
        owner = None
    if isinstance(owner, bytes):
        owner = owner.decode()

    command_id = uuid.uuid4().hex
    ack_key = f"joysafeter:cmd_ack:{command_id}"
    channel = f"joysafeter:cmd:{owner}" if owner else SANDBOX_DESTROY_BROADCAST_CHANNEL
    command: dict[str, Any] = {
        "type": "destroy",
        "sandbox_id": sandbox_id_str,
        "reason": reason,
        "command_id": command_id,
        "ack_key": ack_key,
    }
    if external_id:
        command["external_id"] = external_id

    return await publish_command_and_wait_for_ack(
        redis_client,
        channel,
        command,
        command_id=command_id,
        ack_key=ack_key,
        ack_timeout_seconds=SANDBOX_DESTROY_ACK_TIMEOUT_SECONDS,
        boundary=boundary,
        failure_code=failure_code,
        failure_message=failure_message,
        data={
            "sandbox_id": sandbox_id_str,
            "command_type": "destroy",
            "relay_operation": operation,
            "relay_route": "owner" if owner else "broadcast",
            **(data or {}),
        },
    )


async def _list_runtime_instance_ids(redis_client) -> list[str]:
    instance_ids: list[str] = []
    cursor = 0

    while True:
        cursor, keys = await redis_client.scan(cursor=cursor, match="joysafeter:instances:*", count=100)
        for key in keys:
            if isinstance(key, bytes):
                key = key.decode()
            instance_id = str(key).removeprefix("joysafeter:instances:")
            if instance_id and instance_id != str(key):
                instance_ids.append(instance_id)
        if int(cursor) == 0:
            break

    return sorted(set(instance_ids))


async def relay_environment_image_build_via_redis(
    env_id,
    *,
    version: int,
    packages: dict[str, Any],
    boundary: str,
    operation: str,
    failure_code: str,
    failure_message: str,
    data: dict[str, Any] | None = None,
) -> str | None:
    redis_client = RedisClient.get_client()
    if redis_client is None:
        return None

    try:
        instance_ids = await _list_runtime_instance_ids(redis_client)
    except Exception:
        return None

    env_id_str = str(env_id)
    for instance_id in instance_ids:
        command_id = uuid.uuid4().hex
        ack_key = f"joysafeter:cmd_ack:{command_id}"
        channel = f"joysafeter:cmd:{instance_id}"
        command: dict[str, Any] = {
            "type": "build_environment_image",
            "environment_id": env_id_str,
            "version": version,
            "packages": packages,
            "command_id": command_id,
            "ack_key": ack_key,
        }
        payload = await publish_command_and_wait_for_ack_payload(
            redis_client,
            channel,
            command,
            command_id=command_id,
            ack_key=ack_key,
            ack_timeout_seconds=ENVIRONMENT_IMAGE_BUILD_ACK_TIMEOUT_SECONDS,
            boundary=boundary,
            failure_code=failure_code,
            failure_message=failure_message,
            data={
                "environment_id": env_id_str,
                "image_version": version,
                "relay_operation": operation,
                "runtime_instance_id": instance_id,
                **(data or {}),
            },
        )
        if payload is None:
            continue
        if payload.get("ok"):
            image_tag = payload.get("image_tag")
            return str(image_tag) if image_tag else None
        if payload.get("code") == "IMAGE_BUILDER_UNAVAILABLE":
            continue
        error = str(payload.get("error") or "environment image build failed")
        raise RuntimeError(error)

    return None
