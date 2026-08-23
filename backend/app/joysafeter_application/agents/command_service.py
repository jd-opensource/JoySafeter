from __future__ import annotations

import os
from typing import Any, Optional

from app.joysafeter_application.agents.ports import (
    AgentCredentialBindingPort,
    AgentNameConflictError,
    AgentRepositoryPort,
    AgentUnitOfWork,
)
from app.joysafeter_domain.agents.assets import merge_agent_assets, split_agent_assets
from app.joysafeter_domain.agents.configuration_policy import AgentConfigurationPolicy
from app.joysafeter_domain.agents.snapshots import build_agent_snapshot
from app.joysafeter_domain.llm.compatibility import validate_engine
from app.joysafeter_domain.models.joysafeter_agent import JoySafeterAgent
from app.joysafeter_domain.schemas.joysafeter_agent import (
    JoySafeterCreateAgentRequest,
    JoySafeterUpdateAgentRequest,
)
from app.joysafeter_domain.services.joysafeter_skill_version_access import SkillVersionExposure
from app.joysafeter_shared.common.app_errors import InvalidRequestError, NotFoundError, ResourceConflictError
from app.joysafeter_shared.ids import AgentId, CredentialId, SkillId
from app.joysafeter_shared.utils.datetime import utc_now

_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


class AgentCommandService:
    def __init__(self, uow: AgentUnitOfWork, credential_bindings: AgentCredentialBindingPort) -> None:
        self._uow = uow
        self._repository: AgentRepositoryPort = uow.agents
        self._credential_bindings = credential_bindings

    @staticmethod
    def _mcp_requires_https() -> bool:
        return os.getenv("JOYSAFETER_MCP_REQUIRE_HTTPS", "").strip().lower() in _TRUTHY_ENV_VALUES

    @staticmethod
    def _skill_ref_id(item: Any) -> Optional[SkillId]:
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

    @staticmethod
    def _skill_ref_version(item: Any) -> str:
        value = getattr(item, "version", None)
        if value is None and isinstance(item, dict):
            value = item.get("version")
        normalized = str(value or "latest").strip()
        return normalized or "latest"

    async def _validate_skill_refs(self, skills: list[Any], project_id: Optional[str]) -> list[dict[str, Any]]:
        ref_items = [
            (item, skill_id, self._skill_ref_version(item))
            for item in skills
            for skill_id in [self._skill_ref_id(item)]
            if skill_id is not None
        ]
        refs = [skill_id for _item, skill_id, _version in ref_items]
        if not refs:
            return []
        unique_refs = list(dict.fromkeys(refs))
        skills_by_id = await self._repository.skills_by_ids(unique_refs)
        missing = [str(skill_id) for skill_id in unique_refs if skill_id not in skills_by_id]
        if missing:
            raise InvalidRequestError(
                "Agent references skills that do not exist in this project",
                code="AGENT_SKILL_REF_NOT_FOUND",
                data={"skill_ids": missing},
            )

        cross_project_skills = [
            skill for skill in skills_by_id.values() if project_id is None or skill.project_id != project_id
        ]
        project_org_map: dict[str, str] = {}
        pointer_version_map = {}
        if cross_project_skills:
            project_ids = list(
                dict.fromkeys(
                    [skill.project_id for skill in cross_project_skills]
                    + ([project_id] if project_id is not None else [])
                )
            )
            project_org_map = await self._repository.project_org_ids(project_ids)
            pointer_ids = list(
                dict.fromkeys(
                    pointer_id
                    for skill in cross_project_skills
                    for pointer_id in (skill.org_version_id, skill.public_version_id)
                    if pointer_id is not None
                )
            )
            pointer_version_map = await self._repository.skill_version_strings_by_ids(pointer_ids)

        consumer_org_id = project_org_map.get(project_id) if project_id is not None else None
        exposure_by_skill_id: dict[SkillId, SkillVersionExposure] = {}
        inaccessible = []
        for skill in cross_project_skills:
            exposure = SkillVersionExposure(
                skill_project_id=skill.project_id,
                skill_org_id=project_org_map.get(skill.project_id),
                consumer_project_id=project_id,
                consumer_org_id=consumer_org_id,
                org_version=pointer_version_map.get(skill.org_version_id),
                public_version=pointer_version_map.get(skill.public_version_id),
            )
            exposure_by_skill_id[skill.id] = exposure
            if not exposure.exposed_versions():
                inaccessible.append(str(skill.id))
        if inaccessible:
            raise InvalidRequestError(
                "Agent references skills that are not exposed to this project",
                code="AGENT_SKILL_REF_NOT_FOUND",
                data={"skill_ids": inaccessible},
            )

        latest_ref_ids = list(
            dict.fromkeys(
                skill_id
                for _item, skill_id, version in ref_items
                if version == "latest" and skills_by_id[skill_id].project_id == project_id
            )
        )
        latest_map = await self._repository.latest_skill_versions(latest_ref_ids)
        invalid = []
        normalized: list[dict[str, Any]] = []
        for item, skill_id, version in ref_items:
            skill = skills_by_id[skill_id]
            exposure = exposure_by_skill_id.get(skill_id)
            resolved_version = version
            if version == "draft":
                invalid.append({"skill_id": str(skill_id), "version": version, "reason": "draft_not_allowed"})
            elif version == "latest":
                resolved_version = (
                    exposure.resolve_latest() if exposure is not None else latest_map.get(skill_id)
                ) or ""
                if not resolved_version:
                    invalid.append({"skill_id": str(skill_id), "reason": "no_published_version"})
            elif exposure is not None and not exposure.allows(version):
                invalid.append({"skill_id": str(skill_id), "version": version, "reason": "version_not_exposed"})
            elif exposure is None and not await self._repository.get_skill_version(skill_id, version):
                invalid.append({"skill_id": str(skill_id), "version": version, "reason": "version_not_found"})

            normalized_item = item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            normalized_item["skill_id"] = str(skill_id)
            normalized_item["version"] = resolved_version or version
            normalized.append(normalized_item)
        if invalid:
            raise InvalidRequestError(
                "Agent can only reference published skill versions",
                code="AGENT_SKILL_REF_NOT_PUBLISHED",
                data={"skills": invalid},
            )
        return normalized

    @staticmethod
    def _model_id(model: Any) -> Optional[str]:
        if model is None:
            return None
        if hasattr(model, "id"):
            return str(model.id)
        if isinstance(model, dict):
            value = model.get("id")
            return str(value) if value is not None else None
        return str(model)

    async def _validate_model_credential_ref(
        self,
        model_credential_id: Optional[CredentialId],
        project_id: Optional[str],
        *,
        engine_kind: str,
        model_id: Optional[str],
        acquire_lock: bool = True,
    ) -> None:
        if model_credential_id is None:
            return
        if project_id is None:
            raise NotFoundError(
                code="CREDENTIAL_NOT_FOUND",
                message="Credential not found",
                data={"credential_id": str(model_credential_id)},
            )
        if acquire_lock:
            await self._credential_bindings.lock_credentials([model_credential_id], project_id=project_id)
        await self._credential_bindings.validate_model_reference(
            model_credential_id,
            project_id=project_id,
            engine_kind=engine_kind,
            model_id=model_id,
        )

    async def _lock_environment(self, environment_ref: Optional[str], project_id: Optional[str]) -> None:
        if not environment_ref:
            return
        environment = await self._repository.lock_environment_by_ref(environment_ref, project_id=project_id)
        if environment is None:
            raise InvalidRequestError(
                code="AGENT_ENVIRONMENT_NOT_FOUND",
                message=f"Environment not found: {environment_ref}",
                data={"environment_ref": environment_ref},
                user_action="fix_input",
            )
        if environment.archived_at is not None:
            raise ResourceConflictError(
                code="ENVIRONMENT_ARCHIVED",
                message=f"Environment is archived: {environment_ref}",
                data={"environment_ref": environment_ref, "environment_id": str(environment.id)},
                user_action="refresh",
            )

    @staticmethod
    def _name_conflict(name: str) -> ResourceConflictError:
        return ResourceConflictError(
            code="AGENT_NAME_CONFLICT",
            message=f"Agent with name '{name}' already exists in this project.",
            data={"name": name},
            user_action="fix_input",
        )

    async def create_agent(
        self, req: JoySafeterCreateAgentRequest, project_id: Optional[str] = None
    ) -> JoySafeterAgent:
        try:
            return await self._create_agent(req, project_id=project_id)
        except Exception:
            await self._uow.rollback()
            raise

    async def _create_agent(
        self, req: JoySafeterCreateAgentRequest, project_id: Optional[str] = None
    ) -> JoySafeterAgent:
        mcp_servers = [server.model_dump() for server in req.mcp_servers]
        AgentConfigurationPolicy.validate_mcp_servers(
            mcp_servers,
            require_https=self._mcp_requires_https(),
        )
        AgentConfigurationPolicy.validate_tool_mcp_references(req.tools, mcp_servers)
        validate_engine(req.engine_kind.value)
        await self._lock_environment(req.environment_ref, project_id)
        normalized_skills = await self._validate_skill_refs(list(req.skills or []), project_id)
        await self._validate_model_credential_ref(
            req.model_credential_id,
            project_id,
            engine_kind=req.engine_kind.value,
            model_id=self._model_id(req.model),
        )
        model_data = req.model if isinstance(req.model, str) else req.model.model_dump() if req.model else None
        agent = JoySafeterAgent(
            name=req.name,
            engine_kind=req.engine_kind.value,
            model=model_data,
            system_prompt=req.system,
            description=req.description,
            metadata_=req.metadata,
            env=req.env,
            mcp_servers=mcp_servers,
            skills=merge_agent_assets(normalized_skills, req.agents, req.commands),
            tools=[tool.model_dump() for tool in req.tools],
            multiagent=req.multiagent,
            version=1,
            environment_ref=req.environment_ref,
            model_credential_id=req.model_credential_id,
            project_id=project_id,
        )
        self._repository.add(agent)
        try:
            await self._repository.flush()
            await self._repository.save_version(agent, build_agent_snapshot(agent))
            await self._uow.commit()
        except AgentNameConflictError as exc:
            raise self._name_conflict(req.name) from exc
        await self._repository.refresh(agent)
        return agent

    async def update_agent(
        self,
        agent_id: AgentId,
        req: JoySafeterUpdateAgentRequest,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterAgent]:
        try:
            return await self._update_agent(agent_id, req, project_id=project_id)
        except Exception:
            await self._uow.rollback()
            raise

    async def _update_agent(
        self,
        agent_id: AgentId,
        req: JoySafeterUpdateAgentRequest,
        project_id: Optional[str] = None,
    ) -> Optional[JoySafeterAgent]:
        agent = await self._repository.lock(agent_id, project_id=project_id)
        if agent is None:
            return None
        if agent.archived_at is not None:
            raise ResourceConflictError(
                code="AGENT_ARCHIVED",
                message="Agent is archived and read-only. Updates are not allowed.",
                data={"agent_id": str(agent_id)},
                user_action="refresh",
            )
        if req.version is not None and agent.version != req.version:
            raise ResourceConflictError(
                code="AGENT_VERSION_CONFLICT",
                message=f"Version conflict: expected {req.version}, got {agent.version}",
                data={"agent_id": str(agent_id), "expected_version": req.version, "actual_version": agent.version},
                user_action="refresh",
            )

        effective_mcp = (
            [server.model_dump() for server in req.mcp_servers]
            if req.mcp_servers is not None
            else agent.mcp_servers or []
        )
        effective_tools = req.tools if req.tools is not None else agent.tools or []
        effective_engine = req.engine_kind.value if req.engine_kind is not None else agent.engine_kind
        effective_model = req.model if req.model is not None else agent.model
        effective_environment_ref = req.environment_ref if req.environment_ref is not None else agent.environment_ref
        credential_supplied = "model_credential_id" in req.model_fields_set
        effective_credential_id = req.model_credential_id if credential_supplied else agent.model_credential_id

        AgentConfigurationPolicy.validate_mcp_servers(
            effective_mcp,
            require_https=self._mcp_requires_https(),
        )
        AgentConfigurationPolicy.validate_tool_mcp_references(effective_tools, effective_mcp)
        validate_engine(effective_engine)
        await self._lock_environment(effective_environment_ref, project_id)

        dependency_ref_changed = (credential_supplied and req.model_credential_id != agent.model_credential_id) or (
            req.environment_ref is not None and req.environment_ref != agent.environment_ref
        )
        if dependency_ref_changed:
            active_tasks = await self._repository.list_active_tasks(agent_id, project_id=project_id)
            if active_tasks:
                raise ResourceConflictError(
                    code="AGENT_ACTIVE_TASKS",
                    message=(
                        "Agent has active tasks. Stop or wait for them before changing "
                        "model_credential_id or environment_ref."
                    ),
                    data={"agent_id": str(agent_id), "active_task_ids": [str(task.id) for task in active_tasks]},
                    retryable=True,
                    user_action="retry",
                )

        binding_inputs_changed = credential_supplied or req.engine_kind is not None or req.model is not None
        if binding_inputs_changed:
            credential_ids = [
                credential_id
                for credential_id in (agent.model_credential_id, effective_credential_id)
                if credential_id is not None
            ]
            if project_id is not None:
                await self._credential_bindings.lock_credentials(credential_ids, project_id=project_id)
            await self._validate_model_credential_ref(
                effective_credential_id,
                project_id,
                engine_kind=effective_engine,
                model_id=self._model_id(effective_model),
                acquire_lock=False,
            )

        changed = False
        for field, value in (
            ("name", req.name),
            ("system_prompt", req.system),
            ("description", req.description),
            ("metadata_", req.metadata),
            ("env", req.env),
            ("multiagent", req.multiagent),
        ):
            if value is not None and value != getattr(agent, field):
                setattr(agent, field, value)
                changed = True
        if req.engine_kind is not None and req.engine_kind.value != agent.engine_kind:
            agent.engine_kind = req.engine_kind.value
            changed = True
        if req.model is not None:
            model_data: Any = req.model if isinstance(req.model, str) else req.model.model_dump()
            if model_data != agent.model:
                agent.model = model_data
                changed = True
        if req.mcp_servers is not None and effective_mcp != agent.mcp_servers:
            agent.mcp_servers = effective_mcp
            changed = True
        if req.skills is not None or req.agents is not None or req.commands is not None:
            current_skills, current_agents, current_commands = split_agent_assets(agent.skills or [])
            new_skills = req.skills if req.skills is not None else current_skills
            new_agents = req.agents if req.agents is not None else current_agents
            new_commands = req.commands if req.commands is not None else current_commands
            normalized_skills = await self._validate_skill_refs(list(new_skills or []), project_id)
            merged = merge_agent_assets(normalized_skills, new_agents, new_commands)
            if merged != (agent.skills or []):
                agent.skills = merged
                changed = True
        if req.tools is not None:
            new_tools = [tool.model_dump() for tool in req.tools]
            if new_tools != agent.tools:
                agent.tools = new_tools
                changed = True
        if req.environment_ref is not None and req.environment_ref != agent.environment_ref:
            agent.environment_ref = req.environment_ref
            changed = True
        if credential_supplied and req.model_credential_id != agent.model_credential_id:
            agent.model_credential_id = req.model_credential_id
            changed = True
        if not changed:
            await self._uow.commit()
            return agent

        agent.version += 1
        agent.updated_at = utc_now()
        target_name = agent.name
        try:
            await self._repository.flush()
            await self._repository.save_version(agent, build_agent_snapshot(agent))
            await self._uow.commit()
        except AgentNameConflictError as exc:
            raise self._name_conflict(target_name) from exc
        await self._repository.refresh(agent)
        return agent
