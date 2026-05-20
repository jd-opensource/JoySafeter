import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, select, update, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.conductor.models.agent import ConductorAgent, ConductorAgentVersion
from app.conductor.models.memory import ConductorSessionMemoryStore
from app.conductor.models.session import ConductorSession, ConductorSessionEvent
from app.conductor.models.task import ConductorTask
from app.conductor.schemas.agent import (
    AgentResponse,
    AgentVersionResponse,
    CreateAgentRequest,
    ModelConfig,
    UpdateAgentRequest,
)
from app.utils.datetime import utc_now


def _merge_packed_items(
    skills: list, agents: list, commands: list
) -> list[dict]:
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


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_agent(self, req: CreateAgentRequest) -> ConductorAgent:
        model_data = None
        if req.model:
            model_data = req.model if isinstance(req.model, dict) else req.model.model_dump()

        agent = ConductorAgent(
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
        )
        self.db.add(agent)
        await self.db.flush()

        await self._save_version(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def get_agent(self, agent_id: uuid.UUID) -> Optional[ConductorAgent]:
        result = await self.db.execute(
            select(ConductorAgent).where(
                and_(
                    ConductorAgent.id == agent_id,
                    ConductorAgent.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def get_agent_by_name(self, name: str) -> Optional[ConductorAgent]:
        result = await self.db.execute(
            select(ConductorAgent).where(
                and_(
                    ConductorAgent.name == name,
                    ConductorAgent.deleted_at.is_(None),
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_agents(
        self,
        limit: int = 20,
        after_id: Optional[uuid.UUID] = None,
    ) -> tuple[list[ConductorAgent], bool]:
        q = select(ConductorAgent).where(ConductorAgent.deleted_at.is_(None))
        if after_id:
            q = q.where(ConductorAgent.id < after_id)
        q = q.order_by(ConductorAgent.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        agents = list(result.scalars().all())
        has_more = len(agents) > limit
        return agents[:limit], has_more

    async def update_agent(
        self, agent_id: uuid.UUID, req: UpdateAgentRequest
    ) -> Optional[ConductorAgent]:
        agent = await self.get_agent(agent_id)
        if not agent:
            return None

        if agent.version != req.version:
            raise ValueError(
                f"Version conflict: expected {req.version}, got {agent.version}"
            )

        changed = False
        if req.name is not None and req.name != agent.name:
            agent.name = req.name
            changed = True
        if req.engine_kind is not None:
            agent.engine_kind = req.engine_kind.value
            changed = True
        if req.model is not None:
            model_data = req.model if isinstance(req.model, dict) else req.model.model_dump()
            agent.model = model_data
            changed = True
        if req.system is not None:
            agent.system_prompt = req.system
            changed = True
        if req.description is not None:
            agent.description = req.description
            changed = True
        if req.metadata is not None:
            agent.metadata_ = req.metadata
            changed = True
        if req.env is not None:
            agent.env = req.env
            changed = True
        if req.mcp_servers is not None:
            agent.mcp_configs = [s.model_dump() for s in req.mcp_servers]
            changed = True
        if req.skills is not None or req.agents is not None or req.commands is not None:
            cur_skills, cur_agents, cur_commands = _split_packed_items(agent.skills or [])
            new_skills = req.skills if req.skills is not None else cur_skills
            new_agents = req.agents if req.agents is not None else cur_agents
            new_commands = req.commands if req.commands is not None else cur_commands
            agent.skills = _merge_packed_items(new_skills, new_agents, new_commands)
            changed = True
        if req.tools is not None:
            agent.tools = [t.model_dump() for t in req.tools]
            changed = True
        if req.multiagent is not None:
            agent.multiagent = req.multiagent
            changed = True
        if req.environment_ref is not None:
            agent.environment_ref = req.environment_ref
            changed = True
        if req.secret_ref is not None:
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
        self, agent_id: uuid.UUID, force: bool = False
    ) -> bool:
        agent = await self.get_agent(agent_id)
        if not agent:
            return False

        if not force:
            from app.conductor.models.task import ConductorTask, TERMINAL_STATUSES
            active_q = select(func.count()).select_from(ConductorTask).where(
                and_(
                    ConductorTask.agent_id == agent_id,
                    ConductorTask.status.notin_([s.value for s in TERMINAL_STATUSES]),
                )
            )
            result = await self.db.execute(active_q)
            if result.scalar() > 0:
                raise ValueError("Agent has active tasks. Use force=true to delete.")

        agent.deleted_at = utc_now()
        await self.db.commit()
        return True

    async def archive_agent(self, agent_id: uuid.UUID) -> bool:
        agent = await self.get_agent(agent_id)
        if not agent:
            return False
        if agent.archived_at:
            return True
        agent.archived_at = utc_now()
        await self.db.commit()
        return True

    async def list_versions(
        self,
        agent_id: uuid.UUID,
        limit: int = 20,
        before_version: Optional[int] = None,
    ) -> tuple[list[ConductorAgentVersion], bool]:
        q = select(ConductorAgentVersion).where(
            ConductorAgentVersion.agent_id == agent_id
        )
        if before_version is not None:
            q = q.where(ConductorAgentVersion.version < before_version)
        q = q.order_by(ConductorAgentVersion.version.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        versions = list(result.scalars().all())
        has_more = len(versions) > limit
        return versions[:limit], has_more

    async def _save_version(self, agent: ConductorAgent) -> None:
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
        version = ConductorAgentVersion(
            agent_id=agent.id,
            version=agent.version,
            snapshot=snapshot,
        )
        self.db.add(version)
        await self.db.flush()

    async def hard_delete_agent(self, agent_id: uuid.UUID) -> None:
        # Get all session IDs for this agent
        session_ids_result = await self.db.execute(
            select(ConductorSession.id).where(ConductorSession.agent_id == agent_id)
        )
        session_ids = list(session_ids_result.scalars().all())

        if session_ids:
            # Delete session events
            await self.db.execute(
                delete(ConductorSessionEvent).where(
                    ConductorSessionEvent.session_id.in_(session_ids)
                )
            )
            # Delete tasks linked to sessions
            await self.db.execute(
                delete(ConductorTask).where(
                    ConductorTask.chat_session_id.in_(session_ids)
                )
            )
            # Delete session memory stores
            await self.db.execute(
                delete(ConductorSessionMemoryStore).where(
                    ConductorSessionMemoryStore.session_id.in_(session_ids)
                )
            )
            # Delete sessions
            await self.db.execute(
                delete(ConductorSession).where(
                    ConductorSession.agent_id == agent_id
                )
            )

        # Delete any tasks directly linked to agent (not via session)
        await self.db.execute(
            delete(ConductorTask).where(ConductorTask.agent_id == agent_id)
        )
        # Delete agent versions
        await self.db.execute(
            delete(ConductorAgentVersion).where(
                ConductorAgentVersion.agent_id == agent_id
            )
        )
        # Delete agent
        await self.db.execute(
            delete(ConductorAgent).where(ConductorAgent.id == agent_id)
        )
        await self.db.commit()

    async def archive_sessions_for_agent(
        self, agent_id: uuid.UUID
    ) -> list[uuid.UUID]:
        # Find non-archived sessions for this agent
        result = await self.db.execute(
            select(ConductorSession.id).where(
                and_(
                    ConductorSession.agent_id == agent_id,
                    ConductorSession.archived_at.is_(None),
                )
            )
        )
        session_ids = list(result.scalars().all())

        if session_ids:
            await self.db.execute(
                update(ConductorSession)
                .where(ConductorSession.id.in_(session_ids))
                .values(archived_at=utc_now(), status="terminated")
            )
            await self.db.commit()

        return session_ids

    async def get_agent_version_snapshot(
        self, agent_id: uuid.UUID, version: int
    ) -> Optional[dict]:
        result = await self.db.execute(
            select(ConductorAgentVersion).where(
                and_(
                    ConductorAgentVersion.agent_id == agent_id,
                    ConductorAgentVersion.version == version,
                )
            )
        )
        ver = result.scalar_one_or_none()
        if ver is None:
            return None
        return ver.snapshot

    async def list_active_tasks_for_agent(
        self, agent_id: uuid.UUID
    ) -> list:
        result = await self.db.execute(
            select(ConductorTask).where(
                and_(
                    ConductorTask.agent_id == agent_id,
                    ConductorTask.status.in_(["pending", "scheduling", "running"]),
                )
            )
        )
        return list(result.scalars().all())
