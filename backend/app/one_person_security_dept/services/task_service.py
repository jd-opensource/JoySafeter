"""Application service for Security Dept task lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from pathlib import Path
from typing import Optional

from app.common.exceptions import BadRequestException, NotFoundException
from app.core.redis import RedisClient
from app.core.settings import settings
from app.models.security_dept_task import SecurityDeptTask
from app.one_person_security_dept.repositories.task_repository import SecurityDeptTaskRepository
from app.one_person_security_dept.schemas import (
    SecurityDeptCreateTaskResponse,
    SecurityDeptTaskListResponse,
    SecurityDeptTaskResponse,
)
from app.one_person_security_dept.services.event_bus import SecurityDeptEventBus
from app.one_person_security_dept.services.policy_service import SecurityDeptPolicyService
from app.one_person_security_dept.services.runner import run_security_dept_task
from app.one_person_security_dept.services.runtime_registry import security_dept_runtime_registry
from app.one_person_security_dept.services.skills_service import SecurityDeptSkillsService

_INSTRUCTION_REDIS_KEY = "security_dept:task:{task_id}:instruction"


class SecurityDeptTaskService:
    """Coordinates task create/list/get/cancel operations."""

    def __init__(self, db):
        self.db = db
        self.repo = SecurityDeptTaskRepository(db)

    @staticmethod
    def _task_to_response(task: SecurityDeptTask) -> SecurityDeptTaskResponse:
        return SecurityDeptTaskResponse(
            id=str(task.id),
            user_id=task.user_id,
            workspace_id=str(task.workspace_id) if task.workspace_id else None,
            scenario=task.scenario,
            profile=task.profile,
            status=task.status,
            target=task.target,
            instruction_preview=task.instruction_preview,
            selected_skills=list(task.selected_skills or []),
            summary_md=task.summary_md,
            error_code=task.error_code,
            error_message=task.error_message,
            started_at=task.started_at,
            finished_at=task.finished_at,
            duration_ms=task.duration_ms,
            token_usage=task.token_usage,
            cost_usd=task.cost_usd,
            execution_stats=task.execution_stats,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )

    @staticmethod
    def _instruction_digest(instruction: str) -> str:
        return hashlib.sha256(instruction.encode("utf-8")).hexdigest()

    @staticmethod
    def _instruction_preview(instruction: str, max_len: int = 500) -> str:
        text = instruction.strip()
        if len(text) <= max_len:
            return text
        return text[:max_len]

    @staticmethod
    async def _store_instruction_temp(task_id: str, instruction: str) -> None:
        if not RedisClient.is_available():
            return
        key = _INSTRUCTION_REDIS_KEY.format(task_id=task_id)
        await RedisClient.set(key, instruction, expire=settings.security_dept_event_ttl_seconds)

    @staticmethod
    async def get_temp_instruction(task_id: str) -> Optional[str]:
        if not RedisClient.is_available():
            return None
        key = _INSTRUCTION_REDIS_KEY.format(task_id=task_id)
        return await RedisClient.get(key)

    async def create_task(
        self,
        *,
        user_id: str,
        scenario: str,
        profile_name: str,
        target: Optional[str],
        instruction: str,
        skill_names: list[str],
        workspace_id: Optional[uuid.UUID],
    ) -> SecurityDeptCreateTaskResponse:
        if not settings.security_dept_enabled:
            raise BadRequestException("Security Dept module is disabled")

        SecurityDeptPolicyService.validate_scenario(scenario)
        profile = SecurityDeptPolicyService.get_profile(profile_name)

        if profile.scenario != scenario:
            raise BadRequestException(f"Profile {profile.name} does not support scenario {scenario}")

        resolved_skill_paths = SecurityDeptSkillsService.resolve_skill_paths(skill_names)
        selected_skills = [Path(path).name for path in resolved_skill_paths]

        task = SecurityDeptTask(
            user_id=user_id,
            workspace_id=workspace_id,
            scenario=scenario,
            profile=profile.name,
            status="queued",
            target=target,
            instruction_digest=self._instruction_digest(instruction),
            instruction_preview=self._instruction_preview(instruction),
            selected_skills=selected_skills,
        )
        await self.repo.add(task)
        await self.db.commit()
        await self.db.refresh(task)

        task_id = str(task.id)
        await self._store_instruction_temp(task_id, instruction)

        await SecurityDeptEventBus.publish(task_id, "status", {"message": "Task queued", "status": "queued"})

        async def _run_task() -> None:
            try:
                await run_security_dept_task(task_id=task_id, profile=profile)
            finally:
                await security_dept_runtime_registry.unregister(task_id)

        bg_task = asyncio.create_task(_run_task(), name=f"security_dept_{task_id}")
        await security_dept_runtime_registry.register(task_id, bg_task)

        return SecurityDeptCreateTaskResponse(task_id=task_id, status=task.status, created_at=task.created_at)

    async def get_task(self, *, task_id: uuid.UUID, user_id: str) -> SecurityDeptTaskResponse:
        task = await self.repo.get_for_user(task_id, user_id)
        if task is None:
            raise NotFoundException("Security Dept task not found")
        return self._task_to_response(task)

    async def list_tasks(
        self,
        *,
        user_id: str,
        page: int,
        page_size: int,
        status: Optional[str],
    ) -> SecurityDeptTaskListResponse:
        if page < 1 or page_size < 1:
            raise BadRequestException("page and page_size must be >= 1")

        items = await self.repo.list_for_user(user_id=user_id, page=page, page_size=page_size, status=status)
        total = await self.repo.count_for_user(user_id=user_id, status=status)

        return SecurityDeptTaskListResponse(
            items=[self._task_to_response(task) for task in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    async def cancel_task(self, *, task_id: uuid.UUID, user_id: str) -> SecurityDeptTaskResponse:
        task = await self.repo.get_for_user(task_id, user_id)
        if task is None:
            raise NotFoundException("Security Dept task not found")

        if task.status in {"completed", "failed", "cancelled"}:
            return self._task_to_response(task)

        task.mark_cancelled()
        await self.db.commit()
        await self.db.refresh(task)

        await security_dept_runtime_registry.cancel(str(task.id))
        await SecurityDeptEventBus.publish(str(task.id), "done", {"status": "cancelled"})

        return self._task_to_response(task)
