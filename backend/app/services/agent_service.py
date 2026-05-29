"""
AgentService — manages Agent lifecycle.
"""

from __future__ import annotations

import re
import uuid
from typing import List, Optional

from loguru import logger
from sqlalchemy import delete, exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.app_errors import NotFoundError, ResourceConflictError
from app.core.model.utils import encrypt_credentials
from app.models.agent import Agent, AgentRelease, AgentVersion
from app.models.agent_run import AgentRun
from app.models.execution import Artifact, Execution, ExecutionEvent
from app.models.task import Task
from app.models.thread import Thread
from app.repositories.agent import AgentRepository, AgentVersionRepository
from app.schemas.agent import CreateAgentRequest, UpdateAgentRequest

from .base import BaseService


def _generate_slug(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    slug = re.sub(r"[\s]+", "-", slug).strip("-")
    return slug or "agent"


class AgentService(BaseService):
    """Manages the Agent entity and its initial version."""

    RESPONSE_RELATIONS = ["current_draft_version", "active_release"]

    def __init__(self, db: AsyncSession):
        super().__init__(db)
        self.agent_repo = AgentRepository(db)
        self.version_repo = AgentVersionRepository(db)

    async def list_agents(self, workspace_id: uuid.UUID) -> List[Agent]:
        return await self.agent_repo.list_by_workspace(workspace_id)

    async def get_agent(self, agent_id: uuid.UUID) -> Agent:
        agent = await self.agent_repo.get(
            agent_id,
            relations=self.RESPONSE_RELATIONS,
        )
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})
        return agent

    async def create_agent(
        self,
        workspace_id: uuid.UUID,
        user_id: str,
        data: CreateAgentRequest,
    ) -> Agent:
        base_slug = _generate_slug(data.name)
        slug = base_slug
        suffix = 1
        while await self.agent_repo.get_by_workspace_and_slug(workspace_id, slug):
            suffix += 1
            slug = f"{base_slug}-{suffix}"

        # Create the Agent
        create_data = {
            "workspace_id": workspace_id,
            "name": data.name,
            "slug": slug,
            "description": data.description,
            "avatar": data.avatar,
            "status": "draft",
            "created_by": user_id,
        }
        if data.custom_env:
            create_data["encrypted_custom_env"] = encrypt_credentials(data.custom_env)

        agent = await self.agent_repo.create(create_data)

        # Create an initial draft AgentVersion (v1)
        version = await self.version_repo.create(
            {
                "agent_id": agent.id,
                "version_number": 1,
                "status": "draft",
                "source_kind": "manual",
                "engine_kind": data.engine_kind,
                "definition_payload": data.definition_payload or {},
                "capability_manifest": data.capability_manifest or {},
                "created_by": user_id,
            }
        )

        # Link the draft version
        await self.agent_repo.update(agent.id, {"current_draft_version_id": version.id})

        await self.commit()
        reloaded = await self.agent_repo.get(agent.id, relations=self.RESPONSE_RELATIONS)
        assert reloaded is not None
        logger.info(f"Created agent {agent.id} ({data.name}) with initial version {version.id}")
        return reloaded

    async def update_agent(
        self,
        agent_id: uuid.UUID,
        data: UpdateAgentRequest,
    ) -> Agent:
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})

        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return agent

        if "custom_env" in update_data:
            raw = update_data.pop("custom_env")
            if raw:
                update_data["encrypted_custom_env"] = encrypt_credentials(raw)
            else:
                update_data["encrypted_custom_env"] = None

        updated = await self.agent_repo.update(agent_id, update_data)
        assert updated is not None
        await self.commit()
        reloaded = await self.agent_repo.get(agent_id, relations=self.RESPONSE_RELATIONS)
        assert reloaded is not None
        return reloaded

    async def delete_agent(self, agent_id: uuid.UUID) -> None:
        """Delete an agent and all dependent records.

        FK dependency chain: Agent → Versions → Releases → Runs → Executions → Events/Artifacts.
        Self-referencing FKs (agent.current_draft_version_id, agent.active_release_id,
        runs.current_execution_id, executions.parent_execution_id) must be nullified
        before their targets are deleted.
        """
        agent = await self.agent_repo.get(agent_id)
        if not agent:
            raise NotFoundError("Agent not found", code="AGENT_NOT_FOUND", data={"agent_id": str(agent_id)})

        db = self.db

        has_tasks = (await db.execute(select(exists().where(Task.agent_id == agent_id)))).scalar()
        if has_tasks:
            raise ResourceConflictError(
                "Cannot delete agent: tasks still reference it",
                code="AGENT_DELETE_TASK_REFERENCE_CONFLICT",
                data={"agent_id": str(agent_id)},
            )

        version_ids = (
            (await db.execute(select(AgentVersion.id).where(AgentVersion.agent_id == agent_id))).scalars().all()
        )

        release_ids = (
            (await db.execute(select(AgentRelease.id).where(AgentRelease.agent_version_id.in_(version_ids))))
            .scalars()
            .all()
            if version_ids
            else []
        )

        release_run_ids = (
            (await db.execute(select(AgentRun.id).where(AgentRun.release_id.in_(release_ids)))).scalars().all()
            if release_ids
            else []
        )

        draft_run_ids = (
            (await db.execute(select(AgentRun.id).where(AgentRun.agent_version_id.in_(version_ids)))).scalars().all()
            if version_ids
            else []
        )

        run_ids = list(dict.fromkeys([*release_run_ids, *draft_run_ids]))

        exec_ids = (
            (await db.execute(select(Execution.id).where(Execution.run_id.in_(run_ids)))).scalars().all()
            if run_ids
            else []
        )

        if exec_ids:
            await db.execute(delete(ExecutionEvent).where(ExecutionEvent.execution_id.in_(exec_ids)))
            await db.execute(delete(Artifact).where(Artifact.execution_id.in_(exec_ids)))
            await db.execute(
                update(Execution).where(Execution.parent_execution_id.in_(exec_ids)).values(parent_execution_id=None)
            )

        if run_ids:
            await db.execute(
                update(AgentRun).where(AgentRun.id.in_(run_ids)).values(current_execution_id=None, thread_id=None)
            )

        if exec_ids:
            await db.execute(delete(Execution).where(Execution.id.in_(exec_ids)))

        if run_ids:
            await db.execute(delete(AgentRun).where(AgentRun.id.in_(run_ids)))

        await db.execute(delete(Thread).where(Thread.agent_id == agent_id))

        await db.execute(
            update(Agent)
            .where(Agent.id == agent_id)
            .values(
                current_draft_version_id=None,
                active_release_id=None,
            )
        )

        if release_ids:
            await db.execute(delete(AgentRelease).where(AgentRelease.id.in_(release_ids)))

        if version_ids:
            await db.execute(delete(AgentVersion).where(AgentVersion.id.in_(version_ids)))

        await db.execute(delete(Agent).where(Agent.id == agent_id))

        await self.commit()
        logger.info(f"Deleted agent {agent_id} and all related records")


# ---------------------------------------------------------------------------
# Conductor Agent Service (appended from app/conductor/services/agent_service.py)
# ---------------------------------------------------------------------------

from datetime import datetime  # noqa: E402
from sqlalchemy import and_, func, delete as sa_delete  # noqa: E402

from app.models.agent import ConductorAgent, ConductorAgentVersion  # noqa: E402
from app.models.conductor_memory import ConductorSessionMemoryStore  # noqa: E402
from app.models.session import ConductorSession, ConductorSessionEvent  # noqa: E402
from app.models.task import ConductorTask  # noqa: E402
from app.schemas.agent import (  # noqa: E402
    AgentResponse as ConductorAgentResponse,
    AgentVersionResponse as ConductorAgentVersionResponse,
    CreateAgentRequest as ConductorCreateAgentRequest,
    ConductorModelConfig,
    UpdateAgentRequest as ConductorUpdateAgentRequest,
)
from app.utils.datetime import utc_now  # noqa: E402


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


class ConductorAgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_agent(self, req: ConductorCreateAgentRequest) -> ConductorAgent:
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
        include_archived: bool = False,
    ) -> tuple[list[ConductorAgent], bool]:
        q = select(ConductorAgent).where(ConductorAgent.deleted_at.is_(None))
        if not include_archived:
            q = q.where(ConductorAgent.archived_at.is_(None))
        if after_id:
            cursor_created_at = select(ConductorAgent.created_at).where(
                ConductorAgent.id == after_id
            ).scalar_subquery()
            q = q.where(ConductorAgent.created_at < cursor_created_at)
        q = q.order_by(ConductorAgent.created_at.desc()).limit(limit + 1)
        result = await self.db.execute(q)
        agents = list(result.scalars().all())
        has_more = len(agents) > limit
        return agents[:limit], has_more

    async def update_agent(
        self, agent_id: uuid.UUID, req: ConductorUpdateAgentRequest
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
            from app.models.task import ConductorTask, TERMINAL_STATUSES
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
        agent.updated_at = utc_now()
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
                sa_delete(ConductorSessionEvent).where(
                    ConductorSessionEvent.session_id.in_(session_ids)
                )
            )
            # Delete tasks linked to sessions
            await self.db.execute(
                sa_delete(ConductorTask).where(
                    ConductorTask.chat_session_id.in_(session_ids)
                )
            )
            # Delete session memory stores
            await self.db.execute(
                sa_delete(ConductorSessionMemoryStore).where(
                    ConductorSessionMemoryStore.session_id.in_(session_ids)
                )
            )
            # Delete sessions
            await self.db.execute(
                sa_delete(ConductorSession).where(
                    ConductorSession.agent_id == agent_id
                )
            )

        # Delete any tasks directly linked to agent (not via session)
        await self.db.execute(
            sa_delete(ConductorTask).where(ConductorTask.agent_id == agent_id)
        )
        # Delete agent versions
        await self.db.execute(
            sa_delete(ConductorAgentVersion).where(
                ConductorAgentVersion.agent_id == agent_id
            )
        )
        # Delete agent
        await self.db.execute(
            sa_delete(ConductorAgent).where(ConductorAgent.id == agent_id)
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
