"""Application orchestration for cron/webhook agent execution."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.ports import CredentialAuditActor
from app.joysafeter_application.credentials.snapshot_service import CreateCredentialAwareSession
from app.joysafeter_application.sessions.creation_service import SessionCreationService
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, SessionStatus
from app.joysafeter_domain.models.joysafeter_task import (
    JOYSAFETER_TERMINAL_STATUSES,
    JoySafeterTask,
)
from app.joysafeter_domain.services.joysafeter_environment_service import EnvironmentService
from app.joysafeter_domain.services.joysafeter_session_service import SessionService
from app.joysafeter_domain.services.joysafeter_trigger_runtime_gate import TriggerRuntimeGate
from app.joysafeter_domain.services.task_submission_service import TaskSubmissionService
from app.joysafeter_shared.common.app_errors import (
    ConflictError,
    NotFoundError,
    RequestValidationAppError,
    ResourceConflictError,
)
from app.joysafeter_shared.ids import EnvironmentId, OrganizationId, ProjectId, SessionId, TriggerId, UserId

_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}")
_SESSION_KEY_MAX_CHARS = 512


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


def render_session_key(session_key: Optional[str], payload: dict[str, Any]) -> Optional[str]:
    """Render a keyed-session-mode key template, or None when the trigger isn't keyed."""
    if not session_key:
        return None
    return _normalize_session_key(render_prompt_template(session_key, payload))


def _normalize_session_key(value: Optional[str]) -> Optional[str]:
    normalized = (value or "").strip()
    if not normalized:
        return None
    return normalized[:_SESSION_KEY_MAX_CHARS]


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
    environment_id: Optional[EnvironmentId]
    timeout_sec: int
    max_retries: int
    project_id: ProjectId | None
    user_id: UserId | None
    org_id: OrganizationId | None
    idempotency_key: str
    session_mode: str = "fresh"
    pinned_session_id: Optional[SessionId] = None
    reusable_session_id: Optional[SessionId] = None
    session_key: Optional[str] = None  # rendered key for keyed session mode
    trigger_id: Optional[TriggerId] = None
    metadata: Optional[dict[str, Any]] = None
    system_prompt: Optional[str] = None


@dataclass(frozen=True)
class AgentTriggerRunResult:
    task: JoySafeterTask
    session: JoySafeterSession
    created: bool


class AgentTriggerExecutor:
    def __init__(self, db: AsyncSession, *, audit_actor: CredentialAuditActor) -> None:
        self.db = db
        self._audit_actor = audit_actor

    async def _lock_trigger_for_submission(self, *, trigger_id: TriggerId, project_id: ProjectId | None) -> None:
        result = await self.db.execute(TriggerRuntimeGate.lock_stmt(trigger_id, project_id))
        if result.scalar_one_or_none() is None:
            raise TriggerRuntimeGate.trigger_not_found_error(trigger_id)

    async def _reuse_session(
        self,
        session: JoySafeterSession,
        *,
        project_id: ProjectId | None,
    ) -> tuple[JoySafeterSession, bool]:
        environment_id = session.environment_id
        if environment_id is not None:
            environment = await EnvironmentService(self.db).get_environment(
                environment_id,
                project_id=project_id,
            )
            if environment is None:
                raise RequestValidationAppError(
                    code="SESSION_ENVIRONMENT_NOT_FOUND",
                    message=f"Environment not found: {environment_id}",
                    data={"environment_id": str(environment_id)},
                    user_action="fix_input",
                )
            if environment.archived_at is not None:
                raise ResourceConflictError(
                    code="ENVIRONMENT_ARCHIVED",
                    message=f"Environment is archived: {environment_id}",
                    data={"environment_id": str(environment.id)},
                    user_action="refresh",
                )
        return session, False

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
            return await self._reuse_session(session, project_id=config.project_id)

        if mode == "reuse":
            session = None
            if config.reusable_session_id is not None:
                session = await session_svc.get_session(config.reusable_session_id, project_id=config.project_id)
                if session is not None and (session.archived_at is not None or session.agent_id != config.agent.id):
                    session = None
            if session is not None and session.status == SessionStatus.IDLE.value:
                return await self._reuse_session(session, project_id=config.project_id)

        keyed_value = _normalize_session_key(config.session_key) if mode == "keyed" else None
        if mode == "keyed" and keyed_value:
            # Bucket by the rendered key: reuse this key's newest idle session, so
            # a shared webhook keeps one thread per customer/chat/repo. Falls
            # through to a fresh session (stamped with the key) when none is
            # reusable — that fresh session becomes canonical for the key.
            conditions = [
                JoySafeterSession.agent_id == config.agent.id,
                JoySafeterSession.archived_at.is_(None),
                JoySafeterSession.metadata_["trigger_session_key"].astext == keyed_value,
            ]
            if config.project_id is not None:
                conditions.append(JoySafeterSession.project_id == config.project_id)
            result = await self.db.execute(
                select(JoySafeterSession).where(*conditions).order_by(JoySafeterSession.created_at.desc()).limit(1)
            )
            keyed_session = result.scalar_one_or_none()
            if keyed_session is not None and keyed_session.status == SessionStatus.IDLE.value:
                return await self._reuse_session(keyed_session, project_id=config.project_id)

        session_metadata: dict[str, Any] = {
            "trigger_source": config.source,
            **(config.metadata or {}),
        }
        if keyed_value:
            session_metadata["trigger_session_key"] = keyed_value
        session = await SessionCreationService(
            self.db,
            audit_actor=self._audit_actor,
        ).create_from_source(
            CreateCredentialAwareSession(
                project_id=config.project_id,
                agent_id=config.agent.id,
                environment_id=config.environment_id,
                title=f"Triggered: {config.name}",
                metadata=session_metadata,
                caller="trigger",
            )
        )
        return session, True

    async def run(self, config: AgentTriggerRunConfig, *, enforce_user_quota: bool = True) -> AgentTriggerRunResult:
        session_svc = SessionService(self.db)
        submission = TaskSubmissionService(self.db)
        if config.trigger_id is not None:
            await self._lock_trigger_for_submission(trigger_id=config.trigger_id, project_id=config.project_id)
        await submission.enforce_admission(
            project_id=config.project_id,
            user_id=config.user_id,
            enforce_user_quota=enforce_user_quota,
        )
        session, created_session = await self.resolve_session(config)
        active_result = await self.db.execute(
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.chat_session_id == session.id,
                    JoySafeterTask.status.notin_([s.value for s in JOYSAFETER_TERMINAL_STATUSES]),
                )
            )
            .limit(1)
        )
        if active_result.scalar_one_or_none() is not None:
            raise ConflictError(code="CONFLICT", message="Target session already has an active task")
        if config.trigger_id is not None:
            # Re-lock: resolve_session may have created a session, which commits and
            # drops the FOR UPDATE lock taken above — re-acquire before dispatching so
            # a trigger soft-deleted during session creation cannot still fire.
            try:
                await self._lock_trigger_for_submission(trigger_id=config.trigger_id, project_id=config.project_id)
            except NotFoundError:
                if created_session:
                    await session_svc.delete_session(session.id, project_id=config.project_id)
                raise
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
            trigger_id=config.trigger_id,
            auto_created_session_id=session.id if created_session else None,
            enforce_admission=False,
            enforce_user_quota=False,
        )
        if not created and created_session and task.chat_session_id != session.id:
            # Idempotent replay: create_and_dispatch dropped the fresh session we
            # auto-created for this attempt and returned the pre-existing task.
            # Return that task's real session so callers (mark_attempt.last_session_id)
            # never reference the deleted orphan row (FK violation).
            if task.chat_session_id is not None:
                existing = await session_svc.get_session(task.chat_session_id, project_id=config.project_id)
                if existing is not None:
                    session = existing
        return AgentTriggerRunResult(task=task, session=session, created=created)
