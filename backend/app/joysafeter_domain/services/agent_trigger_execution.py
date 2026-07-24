"""Shared execution helpers for schedule/webhook agent triggers."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, SessionStatus
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask, JoySafeterTaskStatus
from app.joysafeter_domain.services.joysafeter_agent_service import JoySafeterAgentService
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
from app.joysafeter_shared.common.app_errors import ConflictError, RequestValidationAppError

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")


def _value_at_path(source: Any, path: list[str]) -> Any:
    current = source
    for segment in path:
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
    return current


def _template_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    import json

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def render_prompt_template(template: str, payload: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        token = match.group(1)
        root, *path = token.split(".")
        value = payload.get(root) if not path else _value_at_path(payload.get(root), path)
        return _template_value(value)

    return _TOKEN_RE.sub(replace, template)


def payload_filter_matches(filter_config: dict[str, Any] | None, payload: dict[str, Any]) -> bool:
    if not filter_config:
        return True
    for key, expected in filter_config.items():
        if not isinstance(key, str) or not key.strip():
            return False
        root, *path = key.split(".")
        actual = payload.get(root) if not path else _value_at_path(payload.get(root), path)
        if _template_value(actual) != _template_value(expected):
            return False
    return True


@dataclass(frozen=True)
class AgentTriggerRunConfig:
    agent: JoySafeterAgent
    name: str
    source: str
    prompt: str
    system_prompt: Optional[str]
    environment_ref: Optional[str]
    timeout_sec: int
    max_retries: int
    project_id: Optional[str]
    user_id: Optional[str]
    org_id: Optional[str]
    idempotency_key: str
    session_mode: str = "fresh"
    pinned_session_id: Optional[uuid.UUID] = None
    reusable_session_id: Optional[uuid.UUID] = None
    schedule_id: Optional[uuid.UUID] = None
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class AgentTriggerRunResult:
    task: JoySafeterTask
    session: JoySafeterSession
    created: bool


class AgentTriggerExecutor:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolve_session(self, config: AgentTriggerRunConfig) -> tuple[JoySafeterSession, bool]:
        session_svc = SessionService(self.db)
        mode = config.session_mode or "fresh"
        if mode == "pinned":
            if config.pinned_session_id is None:
                raise RequestValidationAppError(
                    code="TRIGGER_PINNED_SESSION_REQUIRED",
                    message="pinned session mode requires pinned_session_id",
                    data={},
                    user_action="fix_input",
                )
            session = await session_svc.get_session(config.pinned_session_id, project_id=config.project_id)
            if session is None or session.archived_at is not None:
                raise RequestValidationAppError(
                    code="TRIGGER_PINNED_SESSION_NOT_FOUND",
                    message="Pinned session not found",
                    data={"session_id": str(config.pinned_session_id)},
                    user_action="fix_input",
                )
            if session.agent_id != config.agent.id:
                raise RequestValidationAppError(
                    code="TRIGGER_PINNED_SESSION_AGENT_MISMATCH",
                    message="Pinned session belongs to a different agent",
                    data={"session_id": str(session.id)},
                    user_action="fix_input",
                )
            if session.status != SessionStatus.IDLE.value:
                raise ConflictError(code="CONFLICT", message="Pinned session is not idle")
            return session, False

        if mode == "reuse":
            session = None
            if config.reusable_session_id is not None:
                session = await session_svc.get_session(config.reusable_session_id, project_id=config.project_id)
                if session is not None and (session.archived_at is not None or session.agent_id != config.agent.id):
                    session = None
            if session is not None and session.status == SessionStatus.IDLE.value:
                return session, False

        environment = None
        if config.environment_ref:
            environment = await EnvironmentService(self.db).get_environment_by_ref(
                config.environment_ref,
                project_id=config.project_id,
            )
        session = await session_svc.create_session(
            agent_id=config.agent.id,
            title=f"Triggered: {config.name}",
            environment_ref=config.environment_ref,
            agent_version=getattr(config.agent, "version", None),
            agent_snapshot=JoySafeterAgentService.build_execution_snapshot(
                config.agent,
                environment=environment,
                environment_ref=config.environment_ref,
            ),
            project_id=config.project_id,
            metadata={
                "trigger_source": config.source,
                **(config.metadata or {}),
            },
        )
        return session, True

    async def run(self, config: AgentTriggerRunConfig, *, enforce_user_quota: bool = True) -> AgentTriggerRunResult:
        session_svc = SessionService(self.db)
        submission = TaskSubmissionService(self.db)
        await submission.enforce_admission(
            project_id=config.project_id,
            user_id=config.user_id,
            enforce_user_quota=enforce_user_quota,
        )
        session, created_session = await self.resolve_session(config)
        active_result = await self.db.execute(
            select(JoySafeterTask.id).where(
                and_(
                    JoySafeterTask.chat_session_id == session.id,
                    JoySafeterTask.status.notin_([s.value for s in JOYSAFETER_TERMINAL_STATUSES]),
                )
            ).limit(1)
        )
        if active_result.scalar_one_or_none() is not None:
            raise ConflictError(code="CONFLICT", message="Target session already has an active task")
        task, created = await submission.create_and_dispatch(
            agent_id=config.agent.id,
            prompt=config.prompt,
            system_prompt=config.system_prompt,
            chat_session_id=session.id,
            session_svc=session_svc,
            timeout_sec=config.timeout_sec,
            max_retries=config.max_retries,
            project_id=config.project_id,
            user_id=config.user_id,
            org_id=config.org_id,
            idempotency_key=config.idempotency_key,
            schedule_id=config.schedule_id,
            auto_created_session_id=session.id if created_session else None,
            enforce_admission=False,
            enforce_user_quota=False,
        )
        return AgentTriggerRunResult(task=task, session=session, created=created)
