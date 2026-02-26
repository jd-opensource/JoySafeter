"""API router for One Person Security Dept."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import shutil
import uuid
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser, CurrentUserWithCSRF
from app.common.response import success_response
from app.core.database import AsyncSessionLocal, get_db
from app.core.redis import RedisClient
from app.core.settings import settings
from app.one_person_security_dept.claude_agent_sdk_python import has_vendored_sdk_source
from app.one_person_security_dept.schemas import (
    SecurityDeptCancelTaskResponse,
    SecurityDeptCreateTaskResponse,
    SecurityDeptHealthResponse,
    SecurityDeptProfileItem,
    SecurityDeptProfilesResponse,
    SecurityDeptSkillFsItem,
    SecurityDeptSkillFsResponse,
    SecurityDeptTaskCreateRequest,
    SecurityDeptTaskListResponse,
    SecurityDeptTaskResponse,
)
from app.one_person_security_dept.services.event_bus import SecurityDeptEventBus
from app.one_person_security_dept.services.policy_service import SecurityDeptPolicyService
from app.one_person_security_dept.services.skills_service import SecurityDeptSkillsService
from app.one_person_security_dept.services.task_service import SecurityDeptTaskService

router = APIRouter(prefix="/v1/security-dept", tags=["One Person Security Dept"])

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def _to_sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _is_sdk_installed() -> bool:
    if has_vendored_sdk_source():
        return True
    return importlib.util.find_spec("claude_agent_sdk") is not None


def _is_cli_found(cli_path: str | None, sdk_installed: bool) -> bool:
    if cli_path:
        if shutil.which(cli_path):
            return True
        return Path(cli_path).exists()
    # claude-agent-sdk bundles a CLI binary, so SDK presence is enough in default mode.
    return sdk_installed


async def _load_task_for_user(task_id: uuid.UUID, user_id: str) -> SecurityDeptTaskResponse:
    async with AsyncSessionLocal() as db:
        service = SecurityDeptTaskService(db)
        return await service.get_task(task_id=task_id, user_id=user_id)


@router.get("/health")
async def health() -> dict:
    sdk_installed = _is_sdk_installed()
    configured_cli_path = settings.security_dept_claude_cli_path
    response = SecurityDeptHealthResponse(
        enabled=settings.security_dept_enabled,
        redis_available=RedisClient.is_available(),
        sdk_installed=sdk_installed,
        cli_found=_is_cli_found(configured_cli_path, sdk_installed),
        configured_cli_path=configured_cli_path,
        max_concurrent_tasks=settings.security_dept_max_concurrent_tasks,
        timeout_seconds=settings.security_dept_task_timeout_seconds,
        workdir_root=settings.security_dept_workdir_root,
    )
    return success_response(data=response.model_dump(mode="json"))


@router.get("/profiles")
async def list_profiles() -> dict:
    items = [
        SecurityDeptProfileItem(
            name=profile.name,
            description=profile.description,
            permission_mode=profile.permission_mode,
            scenario=profile.scenario,
        )
        for profile in SecurityDeptPolicyService.list_profiles()
    ]
    response = SecurityDeptProfilesResponse(items=items)
    return success_response(data=response.model_dump(mode="json"))


@router.get("/skills/fs")
async def list_fs_skills(
    _current_user: CurrentUser,
) -> dict:
    root, items = SecurityDeptSkillsService.list_fs_skills()
    response = SecurityDeptSkillFsResponse(
        root_path=str(root),
        items=[SecurityDeptSkillFsItem(**item) for item in items],
    )
    return success_response(data=response.model_dump(mode="json"))


@router.post("/tasks")
async def create_task(
    payload: SecurityDeptTaskCreateRequest,
    current_user: CurrentUserWithCSRF,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = SecurityDeptTaskService(db)
    result = await service.create_task(
        user_id=current_user.id,
        scenario=payload.scenario,
        profile_name=payload.profile,
        target=payload.target,
        instruction=payload.instruction,
        skill_names=payload.skill_names,
        workspace_id=payload.workspace_id,
    )
    return success_response(
        data=SecurityDeptCreateTaskResponse(**result.model_dump()).model_dump(mode="json"),
        message="Security Dept task created",
    )


@router.get("/tasks")
async def list_tasks(
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = SecurityDeptTaskService(db)
    result = await service.list_tasks(
        user_id=current_user.id,
        page=page,
        page_size=page_size,
        status=status,
    )
    return success_response(data=SecurityDeptTaskListResponse(**result.model_dump()).model_dump(mode="json"))


@router.get("/tasks/{task_id}")
async def get_task(
    task_id: uuid.UUID,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = SecurityDeptTaskService(db)
    result = await service.get_task(task_id=task_id, user_id=current_user.id)
    return success_response(data=SecurityDeptTaskResponse(**result.model_dump()).model_dump(mode="json"))


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: uuid.UUID,
    current_user: CurrentUserWithCSRF,
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = SecurityDeptTaskService(db)
    result = await service.cancel_task(task_id=task_id, user_id=current_user.id)
    response = SecurityDeptCancelTaskResponse(task_id=str(result.id), status=result.status)
    return success_response(data=response.model_dump(mode="json"))


@router.get("/tasks/{task_id}/events")
async def stream_task_events(
    task_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    task_id_str = str(task_id)

    async def event_generator() -> AsyncIterator[str]:
        # Emit latest task status first so the client can hydrate quickly.
        current = await _load_task_for_user(task_id, current_user.id)
        yield _to_sse(
            SecurityDeptEventBus.build_event(
                task_id_str,
                "status",
                {
                    "status": current.status,
                    "message": f"Task status: {current.status}",
                },
            )
        )

        if current.summary_md:
            yield _to_sse(SecurityDeptEventBus.build_event(task_id_str, "summary", {"summary_md": current.summary_md}))

        if current.status in _TERMINAL_STATUSES:
            yield _to_sse(SecurityDeptEventBus.build_event(task_id_str, "done", {"status": current.status}))
            return

        if not RedisClient.is_available() or RedisClient.get_client() is None:
            # Fallback mode: polling status changes when Redis pub/sub is unavailable.
            last_status = current.status
            last_summary = current.summary_md
            while not await request.is_disconnected():
                await asyncio.sleep(1.0)
                latest = await _load_task_for_user(task_id, current_user.id)
                if latest.status != last_status:
                    last_status = latest.status
                    yield _to_sse(
                        SecurityDeptEventBus.build_event(
                            task_id_str,
                            "status",
                            {
                                "status": latest.status,
                                "message": f"Task status: {latest.status}",
                            },
                        )
                    )
                if latest.summary_md and latest.summary_md != last_summary:
                    last_summary = latest.summary_md
                    yield _to_sse(
                        SecurityDeptEventBus.build_event(task_id_str, "summary", {"summary_md": latest.summary_md})
                    )
                if latest.status in _TERMINAL_STATUSES:
                    yield _to_sse(SecurityDeptEventBus.build_event(task_id_str, "done", {"status": latest.status}))
                    return
            return

        redis_client = RedisClient.get_client()
        assert redis_client is not None
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(SecurityDeptEventBus.channel(task_id_str))

        try:
            keepalive_deadline = asyncio.get_running_loop().time() + 15
            while not await request.is_disconnected():
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    payload = message.get("data")
                    if payload:
                        payload_str = payload if isinstance(payload, str) else str(payload)
                        yield f"data: {payload_str}\n\n"
                        try:
                            parsed = json.loads(payload_str)
                        except json.JSONDecodeError:
                            parsed = {}
                        if parsed.get("type") == "done":
                            return
                    keepalive_deadline = asyncio.get_running_loop().time() + 15
                    continue

                now = asyncio.get_running_loop().time()
                if now >= keepalive_deadline:
                    yield ": keep-alive\n\n"
                    keepalive_deadline = now + 15
        finally:
            await pubsub.unsubscribe(SecurityDeptEventBus.channel(task_id_str))
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
