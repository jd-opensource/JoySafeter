"""Bridge JoySafeter task events into EverOS agent memory.

Sandbox agents can call EverOS directly, but agent-case extraction needs the
actual structured tool trajectory. This bridge submits the persisted
JoySafeter session events after a task completes.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime
from typing import Any, Iterable

import httpx
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_project import Project
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_task import JoySafeterTask
from app.joysafeter_orchestrator.kernel.everos_identity import (
    resolve_everos_user_id_for_session,
)
from app.joysafeter_orchestrator.kernel.harness_input_builder import _everos_path_safe_id
from app.joysafeter_shared.everos_scope import compose_everos_project_id

_AGENT_EVENT_TYPES = [
    "agent.message",
    "agent.tool_use",
    "agent.mcp_tool_use",
    "agent.custom_tool_use",
    "agent.tool_result",
    "agent.mcp_tool_result",
]


def _resolve_everos_base_url() -> str:
    return os.getenv("EVEROS_INTERNAL_BASE_URL") or os.getenv(
        "EVEROS_BASE_URL", "http://everos:8003"
    )


def build_agent_memory_messages(
    *,
    task_prompt: str,
    session_events: Iterable[Any],
    user_id: str,
    agent_id: str,
) -> list[dict[str, Any]]:
    """Convert JoySafeter session events into EverOS v1 message DTOs."""
    events = list(session_events)
    converted: list[dict[str, Any]] = []
    saw_agent_activity = False

    prompt = (task_prompt or "").strip()
    if prompt:
        converted.append(
            {
                "sender_id": user_id,
                "role": "user",
                "timestamp": _timestamp_ms(
                    getattr(events[0], "created_at", None) if events else None
                ),
                "content": prompt,
            }
        )

    for event in events:
        event_type = getattr(event, "event_type", "")
        payload = getattr(event, "payload", None) or {}
        ts = _timestamp_ms(getattr(event, "created_at", None))

        if event_type in ("agent.tool_use", "agent.mcp_tool_use", "agent.custom_tool_use"):
            call_id = _first_non_empty(
                payload.get("_call_id"),
                payload.get("tool_use_id"),
                payload.get("call_id"),
                payload.get("id"),
                payload.get("request_id"),
            )
            tool_name = str(payload.get("name") or payload.get("tool_name") or "tool")
            if not call_id:
                logger.warning(
                    "everos_agent_bridge_skipped_tool_use_without_call_id",
                    event_id=str(getattr(event, "id", "")),
                    tool_name=tool_name,
                )
                continue
            converted.append(
                {
                    "sender_id": agent_id,
                    "role": "assistant",
                    "timestamp": ts,
                    "content": "",
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": _json_arguments(payload.get("input", {})),
                            },
                        }
                    ],
                }
            )
            saw_agent_activity = True
            continue

        if event_type in ("agent.tool_result", "agent.mcp_tool_result"):
            call_id = _first_non_empty(
                payload.get("tool_use_id"),
                payload.get("tool_call_id"),
                payload.get("call_id"),
                payload.get("_call_id"),
            )
            if not call_id:
                logger.warning(
                    "everos_agent_bridge_skipped_tool_result_without_call_id",
                    event_id=str(getattr(event, "id", "")),
                )
                continue
            converted.append(
                {
                    "sender_id": agent_id,
                    "role": "tool",
                    "timestamp": ts,
                    "content": _content_to_text(payload.get("content", "")),
                    "tool_call_id": call_id,
                }
            )
            saw_agent_activity = True
            continue

        if event_type == "agent.message":
            text = _content_to_text(payload.get("content", ""))
            if not text.strip():
                continue
            converted.append(
                {
                    "sender_id": agent_id,
                    "role": "assistant",
                    "timestamp": ts,
                    "content": text,
                }
            )
            saw_agent_activity = True

    if not saw_agent_activity:
        return []
    return converted


async def sync_task_to_everos_agent_memory(
    db: AsyncSession,
    *,
    task_id: uuid.UUID,
    session_id: uuid.UUID,
) -> None:
    """Best-effort submit of a completed task trajectory to EverOS."""
    task = await db.get(JoySafeterTask, task_id)
    if task is None:
        logger.warning("everos_agent_bridge_task_not_found", task_id=str(task_id))
        return

    project_id = await _resolve_everos_project_id(db, task.project_id)
    agent_id = _everos_path_safe_id(str(task.agent_id), "default_agent")
    user_id = await _resolve_everos_user_id(db, session_id)
    everos_session_id = _everos_path_safe_id(str(session_id), "default_session")

    start_seq = await _latest_status_running_seq(db, session_id)
    events = await _list_agent_events(db, session_id, after_seq=start_seq)
    messages = build_agent_memory_messages(
        task_prompt=task.prompt,
        session_events=events,
        user_id=user_id,
        agent_id=agent_id,
    )
    if not messages:
        logger.info(
            "everos_agent_bridge_skipped_no_agent_activity",
            task_id=str(task_id),
            session_id=str(session_id),
        )
        return

    payload = {
        "session_id": everos_session_id,
        "app_id": "joysafeter",
        "project_id": project_id,
        "messages": messages,
    }
    await _post_to_everos(payload)
    logger.info(
        "everos_agent_bridge_submitted",
        task_id=str(task_id),
        session_id=str(session_id),
        everos_session_id=everos_session_id,
        project_id=project_id,
        agent_id=agent_id,
        message_count=len(messages),
        tool_call_count=sum(1 for m in messages if m.get("tool_calls")),
    )


async def _latest_status_running_seq(db: AsyncSession, session_id: uuid.UUID) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(JoySafeterSessionEvent.seq), 0)).where(
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.event_type == "session.status_running",
        )
    )
    return int(result.scalar() or 0)


async def _resolve_everos_project_id(
    db: AsyncSession, project_id: Any | None
) -> str:
    stable_project_id = _everos_path_safe_id(project_id or "default_project", "default_project")
    if not project_id:
        return stable_project_id

    result = await db.execute(
        select(Project.slug).where(Project.id == str(project_id)).limit(1)
    )
    project_slug = result.scalar_one_or_none()
    if not project_slug:
        return stable_project_id
    return compose_everos_project_id(
        project_slug=project_slug,
        project_id=stable_project_id,
    )


async def _resolve_everos_user_id(
    db: AsyncSession,
    session_id: uuid.UUID | None,
) -> str:
    return await resolve_everos_user_id_for_session(db, session_id)


async def _list_agent_events(
    db: AsyncSession, session_id: uuid.UUID, *, after_seq: int
) -> list[JoySafeterSessionEvent]:
    result = await db.execute(
        select(JoySafeterSessionEvent)
        .where(
            JoySafeterSessionEvent.session_id == session_id,
            JoySafeterSessionEvent.seq > after_seq,
            JoySafeterSessionEvent.event_type.in_(_AGENT_EVENT_TYPES),
        )
        .order_by(JoySafeterSessionEvent.seq.asc(), JoySafeterSessionEvent.id.asc())
        .limit(500)
    )
    return list(result.scalars().all())


async def _post_to_everos(payload: dict[str, Any]) -> None:
    base_url = _resolve_everos_base_url().rstrip("/")
    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        add_resp = await client.post(f"{base_url}/api/v1/memory/add", json=payload)
        add_resp.raise_for_status()
        flush_resp = await client.post(
            f"{base_url}/api/v1/memory/flush",
            json={
                "session_id": payload["session_id"],
                "app_id": payload["app_id"],
                "project_id": payload["project_id"],
            },
        )
        flush_resp.raise_for_status()


def _timestamp_ms(value: Any) -> int:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp() * 1000)
    return int(datetime.now(tz=UTC).timestamp() * 1000)


def _content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text is not None:
                    parts.append(str(text))
                elif "content" in item:
                    parts.append(_content_to_text(item["content"]))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    if content is None:
        return ""
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _json_arguments(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is not None and str(value):
            return str(value)
    return ""
