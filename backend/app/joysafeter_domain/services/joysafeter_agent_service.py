"""
AgentService — manages Agent lifecycle (v2 JoySafeterAgent).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, cast

from sqlalchemy import and_, func, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent, JoySafeterAgentVersion
from app.joysafeter_domain.models.joysafeter_memory import JoySafeterSessionMemoryStore
from app.joysafeter_domain.models.joysafeter_session import JoySafeterSession, JoySafeterSessionEvent
from app.joysafeter_domain.models.joysafeter_skill import JoySafeterSkill
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.pagination import apply_created_at_desc_cursor
from app.joysafeter_domain.repositories.joysafeter_skill_version import SkillVersionRepository
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
)
from app.joysafeter_domain.services.joysafeter_skill_security import is_skill_usable
from app.joysafeter_shared.common.app_errors import InvalidRequestError
from app.joysafeter_shared.utils.datetime import utc_now  # noqa: E402

TERMINAL_TASK_STATUSES = [s.value for s in JOYSAFETER_TERMINAL_STATUSES]


def _merge_packed_items(skills: list, agents: list, commands: list) -> list[dict]:
    merged = []
    for item in skills:
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        d["target"] = "skills"
        merged.append(d)
    for item in agents:
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        d["target"] = "agents"
        merged.append(d)
    for item in commands:
        d = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        d["target"] = "commands"
        merged.append(d)
    return merged


def _split_packed_items(merged: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    skills, agents, commands = [], [], []
    for item in merged:
        item_copy = {k: v for k, v in item.items() if k != "target"}
        target = item.get("target", "skills")
        if target == "agents":
            agents.append(item_copy)
        elif target == "commands":
            commands.append(item_copy)
        else:
            skills.append(item_copy)
    return skills, agents, commands


class JoySafeterAgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def build_environment_execution_snapshot(environment: Any, *, environment_ref: Optional[str]) -> Optional[dict]:
        if environment is None:
            return None
        environment_id = getattr(environment, "id", None)
        return {
            "ref": environment_ref,
            "id": str(environment_id) if environment_id is not None else None,
            "name": getattr(environment, "name", None),
            "config": getattr(environment, "config", None) or {},
            "image_tag": getattr(environment, "image_tag", None),
            "image_version": getattr(environment, "image_version", None),
        }

    @staticmethod
    def build_execution_snapshot(
        agent: JoySafeterAgent,
        *,
        environment: Any = None,
        environment_ref: Optional[str] = None,
        version: Optional[int] = None,
    ) -> dict:
        skills, agents, commands = _split_packed_items(agent.skills or [])
        effective_environment_ref = environment_ref if environment_ref is not None else agent.environment_ref
        snapshot = {
            "schema": "joysafeter.agent_execution_snapshot.v1",
            "id": str(agent.id),
            "version": version if version is not None else agent.version,
            "name": agent.name,
            "engine_kind": agent.engine_kind,
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "description": agent.description,
            "metadata": agent.metadata_,
            "env": agent.env,
            "mcp_configs": agent.mcp_configs,
            "skills": skills,
            "agents": agents,
            "commands": commands,
            "tools": agent.tools,
            "permission_mode": agent.permission_mode,
            "multiagent": agent.multiagent,
            "environment_ref": effective_environment_ref,
            "secret_ref": agent.secret_ref,
        }
        environment_snapshot = JoySafeterAgentService.build_environment_execution_snapshot(
            environment,
            environment_ref=effective_environment_ref,
        )
        if environment_snapshot is not None:
            snapshot["environment"] = environment_snapshot
        return snapshot

    def _skill_ref_id(self, item: Any) -> Optional[uuid.UUID]:
        value = getattr(item, "skill_id", None)
        if value is None and isinstance(item, dict):
            value = item.get("skill_id")
        if not value:
            return None
        try:
            return uuid.UUID(str(value).removeprefix("skill_"))
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
                        invalid.append({"skill_id": str(skill_id), "reason": reason})
                else:
                    if skill.lifecycle_status != "approved":
                        invalid.append({"skill_id": str(skill_id), "reason": "skill_not_approved"})
        if invalid:
            raise InvalidRequestError(
                "Agent can only reference published, runtime-ready skills",
                code="AGENT_SKILL_REF_NOT_RUNTIME_READY",
                data={"skills": invalid},
            )

    async def _count_active_tasks_for_agent(self, agent_id: uuid.UUID, project_id: Optional[str] = None) -> int:
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
        session_ids: list[uuid.UUID],
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
            mcp_configs=[s.model_dump() for s in req.mcp_servers],
            skills=_merge_packed_items(req.skills, req.agents, req.commands),
            tools=[t.model_dump() for t in req.tools],
            multiagent=req.multiagent,
            version=1,
            environment_ref=req.environment_ref,
            secret_ref=req.secret_ref,
            project_id=project_id,
        )
        self.db.add(agent)
        await self.db.flush()

        await self._save_version(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def get_agent(self, agent_id: uuid.UUID, project_id: Optional[str] = None) -> Optional[JoySafeterAgent]:
        conditions = [
            JoySafeterAgent.id == agent_id,
            JoySafeterAgent.deleted_at.is_(None),
        ]
        if project_id is not None:
            conditions.append(JoySafeterAgent.project_id == project_id)
        result = await self.db.execute(select(JoySafeterAgent).where(and_(*conditions)))
        return result.scalar_one_or_none()

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
        after_id: Optional[uuid.UUID] = None,
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
        agent_id: uuid.UUID,
        req: JoySafeterUpdateAgentRequest,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterAgent]:
        agent = await self.get_agent(agent_id, project_id=project_id)
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
            if new_mcp != agent.mcp_configs:
                agent.mcp_configs = new_mcp
                changed = True
        if req.skills is not None or req.agents is not None or req.commands is not None:
            cur_skills, cur_agents, cur_commands = _split_packed_items(agent.skills or [])
            new_skills = req.skills if req.skills is not None else cur_skills
            new_agents = req.agents if req.agents is not None else cur_agents
            new_commands = req.commands if req.commands is not None else cur_commands
            await self._validate_skill_refs(list(new_skills or []), project_id)
            merged = _merge_packed_items(new_skills, new_agents, new_commands)
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
        if req.secret_ref is not None and req.secret_ref != agent.secret_ref:
            agent.secret_ref = req.secret_ref
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
        agent_id: uuid.UUID,
        force: bool = False,
        project_id: Optional[str] = None,
    ) -> bool:
        agent = await self.get_agent(agent_id, project_id=project_id)
        if not agent:
            return False

        if not force:
            if await self._count_active_tasks_for_agent(agent_id, project_id=project_id) > 0:
                raise ValueError("Agent has active tasks. Use force=true to delete.")

        agent.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_agent_with_sessions(
        self, agent_id: uuid.UUID, project_id: Optional[str] = None
    ) -> tuple[bool, list[uuid.UUID]]:
        """Archive an agent and its live sessions in one transaction.

        Either the agent row and all its non-archived sessions flip to archived
        together, or neither does — a single commit avoids the split state where
        sessions were archived but the agent was not (or vice versa).

        Returns (archived, archived_session_ids). archived is False when the
        agent does not exist; True (with an empty list) when already archived.
        """
        agent = await self.get_agent(agent_id, project_id=project_id)
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
        from app.joysafeter_domain.services.joysafeter_schedule_service import JoySafeterScheduleService

        await JoySafeterScheduleService(self.db).pause_for_agent_archive(agent_id)
        agent.archived_at = now
        agent.updated_at = now
        await self.db.commit()
        return True, session_ids

    async def list_versions(
        self,
        agent_id: uuid.UUID,
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

    async def hard_delete_agent(self, agent_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        agent = await self.get_agent(agent_id, project_id=project_id)
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
        # Delete agent versions
        await self.db.execute(sa_delete(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id))
        # Delete agent
        await self.db.execute(sa_delete(JoySafeterAgent).where(JoySafeterAgent.id == agent_id))
        await self.db.commit()
        return True

    async def archive_sessions_for_agent(
        self, agent_id: uuid.UUID, project_id: Optional[str] = None
    ) -> list[uuid.UUID]:
        if project_id is not None and not await self.get_agent(agent_id, project_id=project_id):
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
        self, agent_id: uuid.UUID, version: int, project_id: Optional[str] = None
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

    async def list_active_tasks_for_agent(self, agent_id: uuid.UUID, project_id: Optional[str] = None) -> list:
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
