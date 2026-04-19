"""
ExecutionRunner — end-to-end orchestrator for CLI agent executions.

Lifecycle:
  1. Get or create container (from pool)
  2. Inject credentials, skills, and CLAUDE.md config
  3. Execute via RuntimeProvider (with session resume if available)
  4. Drain messages → append as ExecutionEvents
  5. Mark final status, store session_id back to pool
  6. Release container back to pool (NOT destroyed)
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.cli_backends.base import CLIMessage, CLIResult, RuntimeSession, build_control_response
from app.core.agent.cli_backends.container_pool import container_pool
from app.core.agent.cli_backends.container_service import (
    CLIContainerService,
    ContainerConfig,
    ContainerInfo,
)
from app.core.agent.cli_backends.injectors import (
    CLISkillInjector,
    RuntimeConfigInjector,
)
from app.core.agent.cli_backends.registry import runtime_registry
from app.core.agent.cli_backends.runner_callbacks import RunnerCallbacks
from app.core.agent.cli_backends.session_registry import session_registry
from app.models.agent_profile import AgentProfile, AgentStatus
from app.models.execution import Execution, MissionExecutionStatus
from app.repositories.agent_profile import AgentProfileRepository
from app.services.execution_service import ExecutionService


class ExecutionRunner:
    """Orchestrates the full lifecycle of a CLI agent execution."""

    def __init__(
        self,
        db: AsyncSession,
        container_service: Optional[CLIContainerService] = None,
        callbacks: Optional[RunnerCallbacks] = None,
    ):
        self.db = db
        self.execution_service = ExecutionService(db)
        self.agent_repo = AgentProfileRepository(db)
        self.container_service = container_service or CLIContainerService()
        self.callbacks = callbacks
        self._auto_approve: bool = True
        self._session: Optional[RuntimeSession] = None

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
        pooled = False  # whether the container came from the pool

        logger.info(
            f"[exec:{execution_id}] Starting execution "
            f"(agent={agent_profile.id if agent_profile else 'none'}, "
            f"runtime={execution.runtime_type})"
        )

        try:
            # 1. Mark as dispatched
            await self.execution_service.mark_status(
                execution_id=execution_id,
                status=MissionExecutionStatus.DISPATCHED,
            )

            # 2. Get or create container
            prior_session_id: Optional[str] = None
            if agent_profile:
                container, prior_session_id = await container_pool.get(agent_profile.id)

            if container:
                pooled = True
                # Verify container is still running
                try:
                    status = await self.container_service.inspect_container(container.container_id)
                    if "running" not in status.strip().lower():
                        logger.warning(
                            f"[exec:{execution_id}] Pooled container {container.container_id[:12]} "
                            f"not running (status={status.strip()}), creating new one"
                        )
                        await container_pool.remove(agent_profile.id)
                        container = None
                        prior_session_id = None
                        pooled = False
                except Exception as inspect_exc:
                    logger.warning(f"[exec:{execution_id}] Failed to inspect pooled container: {inspect_exc}")
                    await container_pool.remove(agent_profile.id)
                    container = None
                    prior_session_id = None
                    pooled = False

            if not container:
                logger.info(f"[exec:{execution_id}] Creating new container")
                container = await self.container_service.create_container(
                    execution_id=execution_id,
                    config=container_config,
                    env=credentials,
                )
                if agent_profile:
                    await container_pool.put(agent_profile.id, container)
                    pooled = True

            if prior_session_id:
                logger.info(
                    f"[exec:{execution_id}] Reusing pooled container "
                    f"{container.container_id[:12]} with session {prior_session_id}"
                )

            await self.execution_service.mark_status(
                execution_id=execution_id,
                status=MissionExecutionStatus.RUNNING,
                container_id=container.container_id,
            )

            if agent_profile:
                await self._update_agent_status(agent_profile, AgentStatus.WORKING)

            # 3. Inject skills and config (idempotent — safe to re-run on reuse)
            await self._inject(
                container_id=container.container_id,
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
                    "reused": prior_session_id is not None,
                },
            )

            # 5. Execute via provider (with session resume + credentials)
            provider = runtime_registry.get(execution.runtime_type)

            # Determine auto_approve from mission settings
            self._auto_approve = await self._get_mission_auto_approve(execution)

            session = await provider.execute(
                prompt,
                container_id=container.container_id,
                cwd=container.working_dir,
                model=model,
                timeout=timeout,
                resume_session_id=prior_session_id,
                env=credentials,
                auto_approve=self._auto_approve,
            )

            # 5b. Register session so the API layer can inject messages
            session_registry.register(execution_id, session)
            self._session = session

            # 6. Drain messages → events
            await self._drain_to_events(execution_id)

            # 7. Await final result
            result = await session.result

            # 8. Mark final status
            await self._finalize(execution_id, result, agent_profile)

            # 9. Store session_id back to pool for next resume
            if result.session_id and agent_profile:
                await container_pool.set_session_id(agent_profile.id, result.session_id)
                logger.info(f"[exec:{execution_id}] Stored session {result.session_id} for agent {agent_profile.id}")

            return result

        except Exception as exc:
            logger.error(f"[exec:{execution_id}] ExecutionRunner error: {exc}")
            await self._mark_failed(execution_id, str(exc), agent_profile)
            return CLIResult(status="failed", error=str(exc))

        finally:
            # 10. Unregister session; release container back to pool
            session_registry.unregister(execution_id)
            if container and agent_profile and pooled:
                await container_pool.release(agent_profile.id)
                logger.info(f"[exec:{execution_id}] Released container {container.container_id[:12]} back to pool")
            elif container:
                await self._cleanup_container(container.container_id)
                logger.info(
                    f"[exec:{execution_id}] Destroyed container {container.container_id[:12]} (no agent profile)"
                )

    async def _get_execution(self, execution_id: uuid.UUID) -> Execution:
        from sqlalchemy import select

        from app.models.execution import Execution as ExecModel

        result = await self.db.execute(select(ExecModel).where(ExecModel.id == execution_id))
        execution = result.scalar_one_or_none()
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")
        return execution

    async def _get_agent_profile(self, execution: Execution) -> Optional[AgentProfile]:
        if not execution.agent_profile_id:
            return None
        return await self.agent_repo.get(execution.agent_profile_id)

    async def _get_mission_auto_approve(self, execution: Execution) -> bool:
        if not execution.mission_id:
            return True
        from sqlalchemy import select

        from app.models.mission import Mission

        result = await self.db.execute(select(Mission.auto_approve).where(Mission.id == execution.mission_id))
        val = result.scalar_one_or_none()
        return val if val is not None else True

    async def _inject(
        self,
        *,
        container_id: str,
        skills: Optional[list[dict[str, Any]]],
        agent_profile: Optional[AgentProfile],
        working_dir: str,
    ) -> None:
        skill_injector = CLISkillInjector(self.container_service)
        config_injector = RuntimeConfigInjector(self.container_service)

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

    _DRAIN_BATCH_SIZE = 10

    async def _drain_to_events(
        self,
        execution_id: uuid.UUID,
    ) -> None:
        assert self._session is not None, "_drain_to_events called before session was set"
        pending: list[tuple[CLIMessage, str, dict[str, Any]]] = []

        async for msg in self._session.iter_messages():
            event_type = self._msg_to_event_type(msg)
            payload = self._msg_to_payload(msg)
            pending.append((msg, event_type, payload))

            needs_flush = len(pending) >= self._DRAIN_BATCH_SIZE or msg.type == "approval_request"
            if needs_flush:
                await self._flush_pending(execution_id, pending)
                pending.clear()

        # Flush remaining events
        if pending:
            await self._flush_pending(execution_id, pending)

    async def _flush_pending(
        self,
        execution_id: uuid.UUID,
        pending: list[tuple[CLIMessage, str, dict[str, Any]]],
    ) -> None:
        try:
            await self.execution_service.batch_append_events(
                execution_id=execution_id,
                events=[{"event_type": event_type, "payload": payload} for _, event_type, payload in pending],
            )
            for msg, _, payload in pending:
                if msg.type == "approval_request":
                    if self._auto_approve:
                        request_id = payload.get("request_id", "")
                        await self._session.inject_message(build_control_response(request_id, "allow"))
                        await self.execution_service.append_event(
                            execution_id=execution_id,
                            event_type="approval_resolved",
                            payload={"decision": "auto_approved", "request_id": request_id},
                        )
                    else:
                        await self.execution_service.mark_status(
                            execution_id=execution_id,
                            status=MissionExecutionStatus.APPROVAL_WAIT,
                        )
                    break
        except Exception as exc:
            logger.warning(f"Failed to flush {len(pending)} events for {execution_id}: {exc}")

    async def _finalize(
        self,
        execution_id: uuid.UUID,
        result: CLIResult,
        agent_profile: Optional[AgentProfile],
    ) -> None:
        if result.status == "completed":
            status = MissionExecutionStatus.COMPLETED
        else:
            status = MissionExecutionStatus.FAILED

        await self.execution_service.append_event(
            execution_id=execution_id,
            event_type="execution_completed" if status == MissionExecutionStatus.COMPLETED else "error",
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

        if self.callbacks:
            try:
                await self.callbacks.on_execution_finalized(execution_id, status, result)
            except Exception as exc:
                logger.warning(f"Callback on_execution_finalized failed for {execution_id}: {exc}")

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
                status=MissionExecutionStatus.FAILED,
                error_message=error[:2000],
            )
        except Exception as exc:
            logger.error(f"Failed to mark execution {execution_id} as failed: {exc}")

        if agent_profile:
            await self._update_agent_status(agent_profile, AgentStatus.ERROR)

        if self.callbacks:
            try:
                await self.callbacks.on_execution_failed(execution_id, error)
            except Exception as exc:
                logger.warning(f"Callback on_execution_failed failed for {execution_id}: {exc}")

    async def _update_agent_status(self, agent_profile: AgentProfile, status: AgentStatus) -> None:
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
            "approval_request": "approval_requested",
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
        if msg.type == "approval_request":
            return {
                "request_id": msg.call_id,
                "subtype": msg.content,
                "tool_name": msg.tool,
                "input": msg.input,
                "message": f"Agent wants to use: {msg.tool or 'unknown tool'}",
            }
        return {"content": msg.content}
