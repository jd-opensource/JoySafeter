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
from app.joysafeter_domain.models.joysafeter_task import JOYSAFETER_TERMINAL_STATUSES, JoySafeterTask
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
)
from app.joysafeter_shared.utils.datetime import utc_now  # noqa: E402


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

    async def _count_active_tasks_for_agent(self, agent_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(JoySafeterTask)
            .where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.notin_([s.value for s in JOYSAFETER_TERMINAL_STATUSES]),
                )
            )
        )
        return cast(int, result.scalar() or 0)

    async def create_agent(
        self, req: JoySafeterCreateAgentRequest, project_id: Optional[str] = None
    ) -> JoySafeterAgent:
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
        if after_id:
            cursor_created_at = (
                select(JoySafeterAgent.created_at).where(JoySafeterAgent.id == after_id).scalar_subquery()
            )
            q = q.where(JoySafeterAgent.created_at < cursor_created_at)
        q = q.order_by(JoySafeterAgent.created_at.desc()).limit(limit + 1)
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
            if await self._count_active_tasks_for_agent(agent_id) > 0:
                raise ValueError("Agent has active tasks. Use force=true to delete.")

        agent.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_agent(self, agent_id: uuid.UUID, project_id: Optional[str] = None) -> bool:
        agent = await self.get_agent(agent_id, project_id=project_id)
        if not agent:
            return False
        if agent.archived_at:
            return True
        if await self._count_active_tasks_for_agent(agent_id) > 0:
            raise ValueError("Agent has active tasks. Stop or cancel them before archiving.")
        agent.archived_at = utc_now()
        agent.updated_at = utc_now()
        await self.db.commit()
        return True

    async def list_versions(
        self,
        agent_id: uuid.UUID,
        limit: int = 20,
        before_version: Optional[int] = None,
    ) -> tuple[list[JoySafeterAgentVersion], bool]:
        q = select(JoySafeterAgentVersion).where(JoySafeterAgentVersion.agent_id == agent_id)
        if before_version is not None:
            q = q.where(JoySafeterAgentVersion.version < before_version)
        q = q.order_by(JoySafeterAgentVersion.version.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        versions = list(result.scalars().all())
        has_more = len(versions) > limit
        return versions[:limit], has_more

    async def _save_version(self, agent: JoySafeterAgent) -> None:
        snapshot = {
            "name": agent.name,
            "engine_kind": agent.engine_kind,
            "model": agent.model,
            "system_prompt": agent.system_prompt,
            "description": agent.description,
            "env": agent.env,
            "mcp_configs": agent.mcp_configs,
            "skills": agent.skills,
            "tools": agent.tools,
            "multiagent": agent.multiagent,
            "environment_ref": agent.environment_ref,
            "secret_ref": agent.secret_ref,
            "metadata": agent.metadata_,
        }
        version = JoySafeterAgentVersion(
            agent_id=agent.id,
            version=agent.version,
            snapshot=snapshot,
        )
        self.db.add(version)
        await self.db.flush()

    async def hard_delete_agent(self, agent_id: uuid.UUID) -> None:
        if await self._count_active_tasks_for_agent(agent_id) > 0:
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

    async def archive_sessions_for_agent(self, agent_id: uuid.UUID) -> list[uuid.UUID]:
        if await self._count_active_tasks_for_agent(agent_id) > 0:
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
            await self.db.execute(
                update(JoySafeterSession)
                .where(JoySafeterSession.id.in_(session_ids))
                .values(archived_at=utc_now(), status="terminated")
            )
            await self.db.commit()

        return session_ids

    async def get_agent_version_snapshot(self, agent_id: uuid.UUID, version: int) -> Optional[dict]:
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

    async def list_active_tasks_for_agent(self, agent_id: uuid.UUID) -> list:
        result = await self.db.execute(
            select(JoySafeterTask).where(
                and_(
                    JoySafeterTask.agent_id == agent_id,
                    JoySafeterTask.status.in_(["pending", "scheduling", "running"]),
                )
            )
        )
        return list(result.scalars().all())
