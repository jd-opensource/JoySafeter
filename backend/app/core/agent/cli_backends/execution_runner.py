"""
ExecutionRunner — end-to-end orchestrator for CLI agent executions.

Lifecycle:
  1. Create container
  2. Inject credentials, skills, and CLAUDE.md config
  3. Execute via RuntimeProvider
  4. Drain messages → append as ExecutionEvents
  5. Mark final status
  6. Destroy container
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.cli_backends.base import CLIMessage, CLIResult, RuntimeSession
from app.core.agent.cli_backends.container_service import (
    CLIContainerService,
    ContainerConfig,
    ContainerInfo,
)
from app.core.agent.cli_backends.injectors import (
    CLISkillInjector,
    CredentialInjector,
    RuntimeConfigInjector,
)
from app.core.agent.cli_backends.registry import runtime_registry
from app.models.agent_profile import AgentProfile, AgentStatus
from app.models.execution import Execution, ExecutionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.services.execution_service import ExecutionService
from app.utils.datetime import utc_now


class ExecutionRunner:
    """Orchestrates the full lifecycle of a CLI agent execution."""

    def __init__(
        self,
        db: AsyncSession,
        container_service: Optional[CLIContainerService] = None,
    ):
        self.db = db
        self.execution_service = ExecutionService(db)
        self.agent_repo = AgentProfileRepository(db)
        self.container_service = container_service or CLIContainerService()

    async def run(
        self,
        *,
        execution_id: uuid.UUID,
        prompt: str,
        credentials: Optional[dict[str, str]] = None,
        skills: Optional[list[dict[str, Any]]] = None,
        container_config: Optional[ContainerConfig] = None,
        model: Optional[str] = None,
        timeout: int = 7200,
    ) -> CLIResult:
        """Run a full execution lifecycle.

        Returns the final CLIResult after the agent completes or fails.
        """
        container: Optional[ContainerInfo] = None
        execution = await self._get_execution(execution_id)
        agent_profile = await self._get_agent_profile(execution)

        try:
            # 1. Mark as dispatched
            await self.execution_service.mark_status(
                execution_id=execution_id,
                status=ExecutionStatus.DISPATCHED,
            )

            # 2. Create container
            container = await self.container_service.create_container(
                execution_id=execution_id,
                config=container_config,
                env=credentials,
            )
            await self.execution_service.mark_status(
                execution_id=execution_id,
                status=ExecutionStatus.RUNNING,
                container_id=container.container_id,
            )

            # 3. Inject credentials, skills, config
            await self._inject(
                container_id=container.container_id,
                credentials=credentials,
                skills=skills,
                agent_profile=agent_profile,
                working_dir=container.working_dir,
            )

            # 4. Record execution_started event
            await self.execution_service.append_event(
                execution_id=execution_id,
                event_type="execution_started",
                payload={
                    "container_id": container.container_id,
                    "runtime_type": execution.runtime_type,
                },
            )

            # 5. Execute via provider
            provider = runtime_registry.get(execution.runtime_type)
            session = await provider.execute(
                prompt,
                container_id=container.container_id,
                cwd=container.working_dir,
                model=model,
                timeout=timeout,
                resume_session_id=execution.prior_session_id,
                env=credentials,
            )

            # 6. Drain messages → events
            await self._drain_to_events(execution_id, session)

            # 7. Await final result
            result = await session.result

            # 8. Mark final status
            await self._finalize(execution_id, result, agent_profile)

            return result

        except Exception as exc:
            logger.error(f"ExecutionRunner error for {execution_id}: {exc}")
            await self._mark_failed(execution_id, str(exc), agent_profile)
            return CLIResult(status="failed", error=str(exc))

        finally:
            # 9. Destroy container
            if container:
                await self._cleanup_container(container.container_id)

    async def _get_execution(self, execution_id: uuid.UUID) -> Execution:
        from sqlalchemy import select
        from app.models.execution import Execution as ExecModel

        result = await self.db.execute(
            select(ExecModel).where(ExecModel.id == execution_id)
        )
        execution = result.scalar_one_or_none()
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")
        return execution

    async def _get_agent_profile(
        self, execution: Execution
    ) -> Optional[AgentProfile]:
        if not execution.agent_profile_id:
            return None
        return await self.agent_repo.get(execution.agent_profile_id)

    async def _inject(
        self,
        *,
        container_id: str,
        credentials: Optional[dict[str, str]],
        skills: Optional[list[dict[str, Any]]],
        agent_profile: Optional[AgentProfile],
        working_dir: str,
    ) -> None:
        cred_injector = CredentialInjector(self.container_service)
        skill_injector = CLISkillInjector(self.container_service)
        config_injector = RuntimeConfigInjector(self.container_service)

        if credentials:
            await cred_injector.inject(container_id, credentials)

        if skills:
            await skill_injector.inject(container_id, skills)

        instructions = agent_profile.instructions if agent_profile else None
        skill_names = None
        if skills:
            skill_names = [s.get("name", "") for s in skills if s.get("name")]

        await config_injector.inject(
            container_id,
            instructions=instructions,
            skill_names=skill_names,
            working_dir=working_dir,
        )

    async def _drain_to_events(
        self, execution_id: uuid.UUID, session: RuntimeSession
    ) -> None:
        async for msg in session.iter_messages():
            event_type = self._msg_to_event_type(msg)
            payload = self._msg_to_payload(msg)
            try:
                await self.execution_service.append_event(
                    execution_id=execution_id,
                    event_type=event_type,
                    payload=payload,
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to append event for {execution_id}: {exc}"
                )

    async def _finalize(
        self,
        execution_id: uuid.UUID,
        result: CLIResult,
        agent_profile: Optional[AgentProfile],
    ) -> None:
        if result.status == "completed":
            status = ExecutionStatus.COMPLETED
        elif result.status == "timeout":
            status = ExecutionStatus.FAILED
        else:
            status = ExecutionStatus.FAILED

        await self.execution_service.append_event(
            execution_id=execution_id,
            event_type="execution_completed" if status == ExecutionStatus.COMPLETED else "error",
            payload={
                "result_summary": {"output_length": len(result.output)},
                "message": result.error or "",
            },
        )

        await self.execution_service.mark_status(
            execution_id=execution_id,
            status=status,
            session_id=result.session_id,
            error_message=result.error if result.error else None,
            result_summary=result.usage,
        )

        if agent_profile:
            await self._update_agent_status(agent_profile, AgentStatus.IDLE)

    async def _mark_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
        agent_profile: Optional[AgentProfile],
    ) -> None:
        try:
            await self.execution_service.append_event(
                execution_id=execution_id,
                event_type="error",
                payload={"message": error},
            )
            await self.execution_service.mark_status(
                execution_id=execution_id,
                status=ExecutionStatus.FAILED,
                error_message=error[:2000],
            )
        except Exception as exc:
            logger.error(f"Failed to mark execution {execution_id} as failed: {exc}")

        if agent_profile:
            await self._update_agent_status(agent_profile, AgentStatus.ERROR)

    async def _update_agent_status(
        self, agent_profile: AgentProfile, status: AgentStatus
    ) -> None:
        try:
            profile = await self.agent_repo.get_for_update(agent_profile.id)
            if profile:
                profile.status = status
                await self.db.commit()
        except Exception as exc:
            logger.warning(f"Failed to update agent status: {exc}")

    async def _cleanup_container(self, container_id: str) -> None:
        try:
            await self.container_service.remove_container(container_id, force=True)
        except Exception as exc:
            logger.warning(f"Failed to cleanup container {container_id[:12]}: {exc}")

    @staticmethod
    def _msg_to_event_type(msg: CLIMessage) -> str:
        mapping = {
            "text": "assistant_text",
            "thinking": "thinking",
            "tool_use": "tool_use_start",
            "tool_result": "tool_use_end",
            "error": "error",
            "artifact": "artifact_created",
        }
        return mapping.get(msg.type, msg.type)

    @staticmethod
    def _msg_to_payload(msg: CLIMessage) -> dict[str, Any]:
        if msg.type == "text":
            return {"content": msg.content}
        if msg.type == "thinking":
            return {"content": msg.content}
        if msg.type == "tool_use":
            return {
                "tool": {
                    "name": msg.tool,
                    "call_id": msg.call_id,
                    "input": msg.input,
                    "status": "running",
                },
            }
        if msg.type == "tool_result":
            return {
                "call_id": msg.call_id,
                "tool_name": msg.tool,
                "output": msg.output,
            }
        if msg.type == "error":
            return {"message": msg.content}
        if msg.type == "artifact":
            return {"artifact": {"content": msg.content}}
        return {"content": msg.content}
