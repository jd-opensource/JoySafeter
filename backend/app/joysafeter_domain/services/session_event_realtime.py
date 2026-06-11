from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

from app.joysafeter_shared.cache.redis import RedisClient
from app.joysafeter_shared.config.service_role import current_role
from app.joysafeter_shared.config.settings import joysafeter_config

logger = logging.getLogger(__name__)


def build_session_event_payload(
    *,
    event_id: uuid.UUID | str | None,
    event_type: str,
    seq: int | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    event: dict[str, Any] = {"type": event_type}
    if event_id:
        raw_id = str(event_id)
        event["id"] = raw_id if raw_id.startswith("evt_") else f"evt_{raw_id}"
    if seq:
        event["seq"] = seq
    if isinstance(payload, dict):
        event.update(payload)
    return event


async def publish_session_event_realtime(
    *,
    session_id: uuid.UUID,
    event_id: uuid.UUID | str | None,
    event_type: str,
    seq: int | None,
    payload: dict[str, Any] | None,
) -> None:
    redis = RedisClient.get_client()
    if redis is None:
        return

    event = build_session_event_payload(
        event_id=event_id,
        event_type=event_type,
        seq=seq,
        payload=payload,
    )
    wrapper = json.dumps(
        {
            "source_instance": f"{joysafeter_config.instance_id}:{current_role().value}:{os.getpid()}",
            "event": event,
        },
        ensure_ascii=False,
        default=str,
    )
    channel = f"joysafeter:session_events:{session_id}"
    try:
        await redis.publish(channel, wrapper)
    except Exception as exc:
        logger.debug("Failed to publish session event realtime", exc_info=exc)
