"""Health probes for the Redis Stream event persistence path."""

from __future__ import annotations

import logging
from typing import Any

from app.joysafeter_shared.config.settings import joysafeter_config

logger = logging.getLogger(__name__)


def _configured_high_water_mark() -> int:
    hwm = joysafeter_config.event_stream_high_water_mark
    if hwm <= 0:
        hwm = int(joysafeter_config.event_stream_max_len * 0.9)
    return max(hwm, 0)


def _pending_count(summary: Any) -> int | None:
    if isinstance(summary, dict):
        value = summary.get("pending")
        return int(value) if value is not None else None
    if isinstance(summary, (list, tuple)) and summary:
        return int(summary[0])
    return None


async def collect_event_stream_health(redis: Any) -> dict[str, Any]:
    """Return operator-facing health for stream backlog and dead letters.

    ``status`` is degraded when durable persistence is still running but needs
    attention. It is unhealthy only when the stream cannot be inspected at all.
    """
    stream_key = joysafeter_config.event_stream_key
    dead_letter_key = f"{stream_key}{joysafeter_config.event_stream_dead_letter_suffix}"
    high_water_mark = _configured_high_water_mark()
    details: dict[str, Any] = {
        "status": "ok",
        "stream_key": stream_key,
        "dead_letter_key": dead_letter_key,
        "high_water_mark": high_water_mark,
    }

    try:
        stream_length = int(await redis.xlen(stream_key))
        dead_letter_length = int(await redis.xlen(dead_letter_key))
    except Exception as exc:
        details["status"] = "unhealthy"
        details["error"] = str(exc)
        return details

    details["stream_length"] = stream_length
    details["dead_letter_length"] = dead_letter_length

    if high_water_mark > 0 and stream_length >= high_water_mark:
        details["status"] = "degraded"
        details["reason"] = "stream_at_high_water_mark"
    if dead_letter_length > 0:
        details["status"] = "degraded"
        details["reason"] = "dead_letters_present"

    try:
        pending = await redis.xpending(stream_key, joysafeter_config.event_stream_group)
        count = _pending_count(pending)
        if count is not None:
            details["pending_count"] = count
    except Exception as exc:
        logger.debug("Redis XPENDING health probe failed: %s", exc)

    return details
