"""
AgentService — manages Agent lifecycle (v2 JoySafeterAgent).
"""

from __future__ import annotations

from typing import Any, Optional, cast

from sqlalchemy import and_, func, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_application.credentials.composition import compose_credential_application
from app.joysafeter_domain.credentials.references import (
    build_agent_execution_snapshot,
    build_environment_execution_snapshot,
)
from app.joysafeter_domain.credentials.types import CredentialId as DomainCredentialId
from app.joysafeter_domain.credentials.types import ProjectId
from app.joysafeter_domain.llm.catalog import get_llm_catalog
from app.joysafeter_domain.llm.model_inference_policy import build_model_inference_policy
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.models.joysafeter_trigger import JoySafeterTrigger
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.repositories.joysafeter_skill_version import SkillVersionRepository
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
)
from app.joysafeter_domain.services.credential_binding_errors import raise_public_credential_error
from app.joysafeter_domain.services.joysafeter_skill_security import is_skill_usable
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError
from app.joysafeter_shared.ids import AgentId, CredentialId, SessionId, SkillId
from app.joysafeter_shared.utils.datetime import utc_now  # noqa: E402

TERMINAL_TASK_STATUSES = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]


def _merge_agent_assets(skills: list, agents: list, commands: list) -> list[dict]:
    merged = []
    # ``mode="json"`` is required: SkillRef.skill_id is a typed ``SkillId`` value
    # object, and this list is stored into the ``skills`` JSONB column whose
    # serializer is the default ``json.dumps`` (no EntityId encoder). A python-mode
    # dump would leave a ``SkillId`` instance in the dict and raise
    # ``TypeError: Object of type SkillId is not JSON serializable`` at flush.
    # JSON mode emits the canonical ``skill_<uuid>`` string the Rust loader and
    # response re-validation both expect.
    for item in skills:
        d = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        d["target"] = "skills"
        merged.append(d)
    for item in agents:
        d = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        d["target"] = "agents"
        merged.append(d)
    for item in commands:
        d = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
        d["target"] = "commands"
        merged.append(d)
    return merged


def _split_agent_assets(merged: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    skills, agents, commands = [], [], []
    for item in merged:
        item_copy = {k: v for k, v in item.items() if k != "target"}
        target = item.get("target")
        if target == "agents":
            agents.append(item_copy)
        elif target == "commands":
            commands.append(item_copy)
        elif target == "skills":
            skills.append(item_copy)
        else:
            raise ValueError("Agent asset target must be skills, agents, or commands")
    return skills, agents, commands


class JoySafeterAgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def build_environment_execution_snapshot(environment: Any, *, environment_ref: Optional[str]) -> Optional[dict]:
        return build_environment_execution_snapshot(environment, environment_ref=environment_ref)

    @staticmethod
    def build_execution_snapshot(
        agent: JoySafeterAgent,
        *,
        environment: Any = None,
        environment_ref: Optional[str] = None,
        version: Optional[int] = None,
    ) -> dict:
        skills, agents, commands = _split_agent_assets(agent.skills or [])
        return build_agent_execution_snapshot(
            agent,
            environment=environment,
            environment_ref=environment_ref,
            version=version,
            split_assets=(skills, agents, commands),
        )

    def _skill_ref_id(self, item: Any) -> Optional[SkillId]:
        value = getattr(item, "skill_id", None)
        if value is None and isinstance(item, dict):
            value = item.get("skill_id")
        if not value:
            return None
        try:
            return SkillId.from_public(str(value))
        except ValueError as exc:
            raise InvalidRequestError(
                "Invalid skill reference id",
                code="AGENT_SKILL_REF_INVALID",
                data={"skill_id": str(value)},
            ) from exc

    def _skill_ref_version(self, item: Any) -> str:
        value = getattr(item, "version", None)
        if value is None and isinstance(item, dict):
            value = item.get("version")
        normalized = str(value or "latest").strip()
        return normalized or "latest"

    async def _validate_skill_refs(self, skills: list[Any], project_id: Optional[str]) -> None:
        ref_items = [
            (skill_id, self._skill_ref_version(item))
            for item in skills
            for skill_id in [self._skill_ref_id(item)]
            if skill_id is not None
        ]
        refs = [skill_id for skill_id, _version in ref_items]
        if not refs:
            return
        unique_refs = list(dict.fromkeys(refs))
        query = select(JoySafeterSkill).where(JoySafeterSkill.id.in_(unique_refs))
        if project_id is not None:
            query = query.where(JoySafeterSkill.project_id == project_id)
        result = await self.db.execute(query)
        skills_by_id = {skill.id: skill for skill in result.scalars().all()}
        missing = [str(skill_id) for skill_id in unique_refs if skill_id not in skills_by_id]
        if missing:
            raise InvalidRequestError(
                "Agent references skills that do not exist in this project",
                code="AGENT_SKILL_REF_NOT_FOUND",
                data={"skill_ids": missing},
            )

        version_repo = SkillVersionRepository(self.db)
        latest_ref_ids = list(dict.fromkeys(skill_id for skill_id, version in ref_items if version == "latest"))
        latest_map = await version_repo.latest_version_map(latest_ref_ids)
        invalid = []
        for skill_id, version in ref_items:
            skill = skills_by_id[skill_id]
            if version == "draft":
                invalid.append({"skill_id": str(skill_id), "version": version, "reason": "draft_not_allowed"})
            elif version == "latest" and not latest_map.get(skill_id):
                invalid.append({"skill_id": str(skill_id), "reason": "no_published_version"})
            elif version != "latest" and not await version_repo.get_by_version(skill_id, version):
                invalid.append({"skill_id": str(skill_id), "version": version, "reason": "version_not_found"})
            else:
                # Agents reference published (frozen) versions, so skip the
                # draft-content drift check that is_skill_usable performs —
                # only verify lifecycle + security status + scan-hash presence.
                # When scanning is globally disabled, skip the security gates
                # entirely — only lifecycle_status matters.
                from app.joysafeter_shared.config import settings as app_settings

                if app_settings.skill_security_scan_enabled:
                    usable, reason = is_skill_usable(skill, check_drift=False)
                    if not usable:
                        invalid.append({"skill_id": str(skill_id), "reason": reason or "skill_unusable"})
                else:
                    if skill.lifecycle_status != "approved":
                        invalid.append({"skill_id": str(skill_id), "reason": "skill_not_approved"})
        if invalid:
            raise InvalidRequestError(
                "Agent can only reference published, runtime-ready skills",
                code="AGENT_SKILL_REF_NOT_RUNTIME_READY",
                data={"skills": invalid},
            )

    async def _validate_model_credential_ref(
        self,
        model_credential_id: Optional[CredentialId],
        project_id: Optional[str],
        *,
        acquire_lock: bool = True,
    ) -> None:
        """Ensure an agent's model_credential_id references a usable model credential.

        The credential must exist in the same project, satisfy model binding
        policy, and remain active. Project-less (global) agents cannot pin a
        project-scoped credential, so a supplied id is rejected outright.
        """
        if model_credential_id is None:
            return
        if project_id is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(model_credential_id)},
            )
        application = compose_credential_application(self.db, auto_commit=False)
        if acquire_lock:
            await application.uow.credentials.lock_credential(model_credential_id, project_id=project_id)
        try:
            binding = build_model_inference_policy(
                get_llm_catalog(),
                project_id=ProjectId(project_id),
                credential_id=DomainCredentialId(str(model_credential_id)),
                engine_kind=self._binding_engine_kind,
                model_id=self._binding_model_id,
            )
            await application.binding_service.validate_model_inference_reference(binding)
        except Exception as exc:
            raise_public_credential_error(exc, credential_id=model_credential_id)

    async def _count_active_tasks_for_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> int:
        if project_id is not None and not await self.get_agent(agent_id, project_id=project_id):
            return 0
        result = await self.db.execute(
            select(func.count())
            .select_from(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.notin_(TERMINAL_TASK_STATUSES),
                )
            )
        )
        return cast(int, result.scalar() or 0)

    async def _archive_session_ids_if_no_active_tasks(
        self,
        session_ids: list[SessionId],
        archived_at,
    ) -> None:
        if not session_ids:
            return
        active_task_exists = (
            select(JoySafeterTask.id)
            .where(
                and_(
                    JoySafeterTask.chat_session_id == JoySafeterSession.id,
                    JoySafeterTask.status.notin_(TERMINAL_TASK_STATUSES),
                )
            )
            .exists()
        )
        result = await self.db.execute(
            update(JoySafeterSession)
            .where(
                and_(
                    JoySafeterSession.id.in_(session_ids),
                    JoySafeterSession.archived_at.is_(None),
                    ~active_task_exists,
                )
            )
            .values(archived_at=archived_at, status="terminated")
        )
        if cast(Any, result).rowcount != len(session_ids):
            await self.db.rollback()
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")

    async def create_agent(
        self, req: JoySafeterCreateAgentRequest, project_id: Optional[str] = None
    ) -> JoySafeterAgent:
        await self._validate_skill_refs(list(req.skills or []), project_id)
        self._binding_engine_kind = req.engine_kind.value
        self._binding_model_id = req.model.id if hasattr(req.model, "id") else req.model
        await self._validate_model_credential_ref(req.model_credential_id, project_id)
        model_data = None
        if req.model:
            model_data = req.model if isinstance(req.model, str) else req.model.model_dump()

        agent = JoySafeterAgent(
            name=req.name,
            engine_kind=req.engine_kind.value,
            model=model_data,
            system_prompt=req.system,
            description=req.description,
            metadata_=req.metadata,
            env=req.env,
            mcp_servers=[s.model_dump() for s in req.mcp_servers],
            skills=_merge_agent_assets(req.skills, req.agents, req.commands),
            tools=[t.model_dump() for t in req.tools],
            multiagent=req.multiagent,
            version=1,
            environment_ref=req.environment_ref,
            model_credential_id=req.model_credential_id,
            project_id=project_id,
        )
        self.db.add(agent)
        try:
            await self.db.flush()
        except Exception as exc:
            if "uq_joysafeter_agents_project_name" in str(exc) or "UniqueViolation" in type(exc).__name__:
                from app.joysafeter_shared.common.app_errors import ConflictError

                raise ConflictError(
                    code="AGENT_NAME_CONFLICT",
                    message=f"Agent with name '{req.name}' already exists in this project.",
                    data={"name": req.name},
                ) from exc
            raise

        await self._save_version(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def get_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]:
        conditions = [
            JoySafeterAgent.id == agent_id,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def lock_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]:
        conditions = [
            JoySafeterAgent.id == agent_id,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(
            select(JoySafeterAgent).where(and_(*conditions)).execution_options(populate_existing=True).with_for_update()
        )
        return result.scalar_one_or_none()

    async def _lock_lifecycle_aggregate(
        self,
        agent_id: AgentId,
        *,
        project_id: Optional[str],
        all_trigger_projects: bool = False,
    ) -> tuple[Any, list[JoySafeterTrigger], Optional[JoySafeterAgent]]:
        """Acquire the shared Trigger→Agent lifecycle lock order.

        Scheduler firing locks Trigger before Snapshot creation locks Agent. Every
        destructive Agent lifecycle path uses the same order before blocker scans,
        Session mutation, Trigger mutation, or deletion decisions.
        """
        from app.joysafeter_domain.services.joysafeter_trigger_service import JoySafeterTriggerService

        trigger_service = JoySafeterTriggerService(self.db)
        trigger_project_id = None if all_trigger_projects else project_id
        triggers = await trigger_service.lock_for_agent_lifecycle(agent_id, project_id=trigger_project_id)
        agent = await self.lock_agent(agent_id, project_id=project_id)
        return trigger_service, triggers, agent

    async def get_agent_by_name(self, name: str, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]:
        conditions = [
            JoySafeterAgent.name == name,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(and_(*conditions)))
        return result.scalar_one_or_none()

    async def list_agents(
        self,
        limit: int = 20,
        after_id: Optional[AgentId] = None,
        include_archived: bool = False,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterAgent], bool]:
        q = select(JoySafeterAgent).where(JoySafeterAgent.deleted_at.is_(None))
        if not include_archived:
            q = q.where(JoySafeterAgent.archived_at.is_(None))
        if project_id is not None:
            q = q.where(JoySafeterAgent.project_id == project_id)
        q = apply_created_at_desc_cursor(q, JoySafeterAgent, after_id).limit(limit + 1)
        result = await self.db.execute(q)
        agents = list(result.scalars().all())
        has_more = len(agents) > limit
        return agents[:limit], has_more

    async def update_agent(
        self,
        agent_id: AgentId,
        req: JoySafeterUpdateAgentRequest,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterAgent]:
        agent = await self.lock_agent(agent_id, project_id=project_id)
        if not agent:
            return None

        if agent.version != req.version:
            raise ValueError(f"Version conflict: expected {req.version}, got {agent.version}")

        changed = False
        if req.name is not None and req.name != agent.name:
            agent.name = req.name
            changed = True
        if req.engine_kind is not None and req.engine_kind.value != agent.engine_kind:
            agent.engine_kind = req.engine_kind.value
            changed = True
        if req.model is not None:
            # ``req.model`` may be a bare model-name string or a structured
            # config; both are stored verbatim in the JSONB ``model`` column.
            model_data: Any = req.model if isinstance(req.model, str) else req.model.model_dump()
            if model_data != agent.model:
                agent.model = model_data
                changed = True
        if req.system is not None and req.system != agent.system_prompt:
            agent.system_prompt = req.system
            changed = True
        if req.description is not None and req.description != agent.description:
            agent.description = req.description
            changed = True
        if req.metadata is not None and req.metadata != agent.metadata_:
            agent.metadata_ = req.metadata
            changed = True
        if req.env is not None and req.env != agent.env:
            agent.env = req.env
            changed = True
        if req.mcp_servers is not None:
            new_mcp = [s.model_dump() for s in req.mcp_servers]
            if new_mcp != agent.mcp_servers:
                agent.mcp_servers = new_mcp
                changed = True
        if req.skills is not None or req.agents is not None or req.commands is not None:
            cur_skills, cur_agents, cur_commands = _split_agent_assets(agent.skills or [])
            new_skills = req.skills if req.skills is not None else cur_skills
            new_agents = req.agents if req.agents is not None else cur_agents
            new_commands = req.commands if req.commands is not None else cur_commands
            await self._validate_skill_refs(list(new_skills or []), project_id)
            merged = _merge_agent_assets(new_skills, new_agents, new_commands)
            if merged != (agent.skills or []):
                agent.skills = merged
                changed = True
        if req.tools is not None:
            new_tools = [t.model_dump() for t in req.tools]
            if new_tools != agent.tools:
                agent.tools = new_tools
                changed = True
        if req.multiagent is not None and req.multiagent != agent.multiagent:
            agent.multiagent = req.multiagent
            changed = True
        if req.environment_ref is not None and req.environment_ref != agent.environment_ref:
            agent.environment_ref = req.environment_ref
            changed = True
        if "model_credential_id" in req.model_fields_set and req.model_credential_id != agent.model_credential_id:
            credential_ids = [
                credential_id
                for credential_id in (agent.model_credential_id, req.model_credential_id)
                if credential_id is not None
            ]
            if project_id is not None:
                await compose_credential_application(self.db, auto_commit=False).uow.credentials.lock_credentials(
                    credential_ids,
                    project_id=project_id,
                )
            self._binding_engine_kind = req.engine_kind.value if req.engine_kind is not None else agent.engine_kind
            selected_model = req.model if req.model is not None else agent.model
            self._binding_model_id = selected_model.id if hasattr(selected_model, "id") else selected_model
            await self._validate_model_credential_ref(
                req.model_credential_id,
                project_id,
                acquire_lock=False,
            )
            agent.model_credential_id = req.model_credential_id
            changed = True

        if not changed:
            return agent

        agent.version += 1
        agent.updated_at = utc_now()
        await self.db.flush()
        await self._save_version(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def delete_agent(
        self,
        agent_id: AgentId,
        force: bool = False,
        project_id: Optional[str] = None,
    ) -> bool:
        trigger_service, triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if not agent:
            return False

        if not force:
            if await self._count_active_tasks_for_agent(agent_id, project_id=project_id) > 0:
                raise ValueError("Agent has active tasks. Use force=true to delete.")

        trigger_service.pause_locked_agent_triggers(triggers)
        agent.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_agent_with_sessions(
        self, agent_id: AgentId, project_id: Optional[str] = None
    ) -> tuple[bool, list[SessionId]]:
        """Archive an agent and its live sessions in one transaction.

        Either the agent row and all its non-archived sessions flip to archived
        together, or neither does — a single commit avoids the split state where
        sessions were archived but the agent was not (or vice versa).

        Returns (archived, archived_session_ids). archived is False when the
        agent does not exist; True (with an empty list) when already archived.
        """
        trigger_service, triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if not agent:
            return False, []
        if agent.archived_at:
            return True, []
        if await self._count_active_tasks_for_agent(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")

        result = await self.db.execute(
            select(JoySafeterSession.id).where(
                and_(
                    JoySafeterSession.agent_id == agent_id,
                    JoySafeterSession.archived_at.is_(None),
                )
            )
        )
        session_ids = list(result.scalars().all())

        now = utc_now()
        await self._archive_session_ids_if_no_active_tasks(session_ids, now)
        trigger_service.pause_locked_agent_triggers(triggers)
        agent.archived_at = now
        agent.updated_at = now
        await self.db.commit()
        return True, session_ids

    async def restore_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        """Un-archive an agent and rearm its paused cron triggers in one transaction.

        Returns False when the agent does not exist (or is out of the given
        project scope). Returns True when restored, or when it was already active
        (idempotent, no side effects). Already-terminated sessions are left as-is.
        """
        trigger_service, triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if not agent:
            return False
        if agent.archived_at is None:
            return True

        now = utc_now()
        agent.archived_at = None
        agent.updated_at = now
        await self.db.flush()  # make cleared archived_at visible to _next_run_or_pause
        await trigger_service.resume_locked_agent_triggers(triggers)
        await self.db.commit()
        return True

    async def list_versions(
        self,
        agent_id: AgentId,
        limit: int = 20,
        before_version: Optional[int] = None,
        project_id: Optional[str] = None,
    ) -> tuple[list[JoySafeterAgentVersion], bool]:
        if project_id is not None and not await self.get_agent(agent_id, project_id=project_id):
            return [], False
        q = select(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id)
        if before_version is not None:
            q = q.where(JoySafeterAgentVersion.version < before_version)
        q = q.order_by(JoySafeterAgentVersion.version.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        versions = list(result.scalars().all())
        has_more = len(versions) > limit
        return versions[:limit], has_more

    async def _save_version(self, agent: JoySafeterAgent) -> None:
        snapshot = self.build_execution_snapshot(agent)
        version = JoySafeterAgentVersion(
            agent_id=agent.id,
            version=agent.version,
            snapshot=snapshot,
        )
        self.db.add(version)
        await self.db.flush()

    async def hard_delete_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> bool:
        _trigger_service, _triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
            all_trigger_projects=True,
        )
        if not agent:
            return False
        if await self._count_active_tasks_for_agent(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Cancel them before hard delete.")

        # Get all session IDs for this agent
        session_ids_result = await self.db.execute(
            select(JoySafeterSession.id).where(JoySafeterSession.agent_id == agent_id)
        )
        session_ids = list(session_ids_result.scalars().all())

        if session_ids:
            # Delete session events
            await self.db.execute(
                sa_delete(JoySafeterSessionEvent).where(JoySafeterSessionEvent.session_id.in_(session_ids))
            )
            # Delete tasks linked to sessions
            await self.db.execute(sa_delete(JoySafeterTask).where(JoySafeterTask.chat_session_id.in_(session_ids)))
            # Delete session memory stores
            await self.db.execute(
                sa_delete(JoySafeterSessionMemoryStore).where(JoySafeterSessionMemoryStore.session_id.in_(session_ids))
            )
            # Delete sessions
            await self.db.execute(sa_delete(JoySafeterSession).where(JoySafeterSession.agent_id == agent_id))

        # Delete any tasks directly linked to agent (not via session)
        await self.db.execute(sa_delete(JoySafeterTask).where(JoySafeterTask.agent_id == agent_id))
        await self.db.execute(sa_delete(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent_id))
        # Delete agent versions
        await self.db.execute(sa_delete(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id))
        # Delete agent
        await self.db.execute(sa_delete(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))
        await self.db.commit()
        return True

    async def archive_sessions_for_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> list[SessionId]:
        _trigger_service, _triggers, agent = await self._lock_lifecycle_aggregate(
            agent_id,
            project_id=project_id,
        )
        if agent is None:
            return []
        if await self._count_active_tasks_for_agent(agent_id, project_id=project_id) > 0:
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving sessions.")

        # Find non-archived sessions for this agent
        result = await self.db.execute(
            select(JoySafeterSession.id).where(
                and_(
                    JoySafeterSession.agent_id == agent_id,
                    JoySafeterSession.archived_at.is_(None),
                )
            )
        )
        session_ids = list(result.scalars().all())

        if session_ids:
            await self._archive_session_ids_if_no_active_tasks(session_ids, utc_now())
            await self.db.commit()

        return session_ids

    async def get_agent_version_snapshot(
        self, agent_id: AgentId, version: int, project_id: Optional[str] = None
    ) -> Optional[dict]:
        if project_id is not None and not await self.get_agent(agent_id, project_id=project_id):
            return None
        result = await self.db.execute(
            select(JoySafeterAgentVersion).where(
                and_(
                    JoySafeterAgentVersion.agent_id == agent_id,
                    JoySafeterAgentVersion.version == version,
                )
            )
        )
        ver = result.scalar_one_or_none()
        if ver is None:
            return None
        return ver.snapshot

    async def count_delete_preview(
        self, agent_id: AgentId, project_id: Optional[str] = None
    ) -> Optional[tuple[int, int, int, int]]:
        """Return (sessions, tasks, versions, triggers) counts for a delete preview.

        Returns None when the agent does not exist (or is out of the given
        project scope), so the caller can surface a 404. Counts are exact
        aggregates (``func.count()``) and are NOT affected by list pagination
        limits:
          - sessions: all sessions for the agent, including archived ones
          - tasks: all tasks for the agent, including terminal history
          - versions: all historical versions
          - triggers: all triggers, including soft-deleted audit rows
        """
        if not await self.get_agent(agent_id, project_id=project_id):
            return None

        sessions_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterSession).where(JoySafeterSession.agent_id == agent_id)
        )
        sessions = cast(int, sessions_result.scalar() or 0)

        tasks_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterTask).where(JoySafeterTask.agent_id == agent_id)
        )
        tasks = cast(int, tasks_result.scalar() or 0)

        versions_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id)
        )
        versions = cast(int, versions_result.scalar() or 0)

        triggers_result = await self.db.execute(
            select(func.count()).select_from(JoySafeterTrigger).where(JoySafeterTrigger.agent_id == agent_id)
        )
        triggers = cast(int, triggers_result.scalar() or 0)

        return sessions, tasks, versions, triggers

    async def list_active_tasks_for_agent(self, agent_id: AgentId, project_id: Optional[str] = None) -> list:
        if project_id is not None and not await self.get_agent(agent_id, project_id=project_id):
            return []
        result = await self.db.execute(
            select(JoySafeterTask).where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.in_(["pending", "scheduling", "running"]),
                )
            )
        )
        return list(result.scalars().all())
