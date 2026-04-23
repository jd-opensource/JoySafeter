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

import asyncio
import uuid
from typing import Any, Optional

from loguru import logger
from sqlalchemy import select
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
from app.models.agent import AgentRelease
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.models.task import Task
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
        run = await self._get_run(execution)
        release = await self._get_release(run)
        pooled = False  # whether the container came from the pool

        logger.info(
            f"[exec:{execution_id}] Starting execution "
            f"(release={release.id}, "
            f"executor={execution.executor_kind})"
        )

        try:
            # 1. Mark as dispatched
            await self._mark_status(execution_id, "dispatched")

            # 2. Get or create container
            prior_session_id: Optional[str] = None
            if release:
                container, prior_session_id = await container_pool.get(release.id)

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
                        await container_pool.remove(release.id)
                        container = None
                        prior_session_id = None
                        pooled = False
                except Exception as inspect_exc:
                    logger.warning(f"[exec:{execution_id}] Failed to inspect pooled container: {inspect_exc}")
                    await container_pool.remove(release.id)
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
                if release:
                    await container_pool.put(release.id, container)
                    pooled = True

            if prior_session_id:
                logger.info(
                    f"[exec:{execution_id}] Reusing pooled container "
                    f"{container.container_id[:12]} with session {prior_session_id}"
                )

            await self._mark_status(execution_id, "running", container_id=container.container_id)

            # 3. Inject skills and config (idempotent — safe to re-run on reuse)
            await self._inject(
                container_id=container.container_id,
                skills=skills,
                release=release,
                working_dir=container.working_dir,
            )

            # 4. Record execution_started event
            await self.execution_service.append_event(
                execution_id=execution_id,
                event_type="execution_started",
                payload={
                    "container_id": container.container_id,
                    "executor_kind": execution.executor_kind,
                    "reused": prior_session_id is not None,
                },
            )

            # 5. Execute via provider (with session resume + credentials)
            provider = runtime_registry.get(execution.executor_kind)

            # Determine auto_approve from task settings
            self._auto_approve = await self._get_auto_approve(execution, run)

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
            await self._finalize(execution_id, result, release)

            # 9. Store session_id back to pool for next resume
            if result.session_id and release:
                await container_pool.set_session_id(release.id, result.session_id)
                logger.info(f"[exec:{execution_id}] Stored session {result.session_id} for release {release.id}")

            return result

        except Exception as exc:
            logger.error(f"[exec:{execution_id}] ExecutionRunner error: {exc}")
            await self._mark_failed(execution_id, str(exc))
            return CLIResult(status="failed", error=str(exc))

        finally:
            # 10. Unregister session; release container back to pool
            session_registry.unregister(execution_id)
            if container and release and pooled:
                await container_pool.release(release.id)
                logger.info(f"[exec:{execution_id}] Released container {container.container_id[:12]} back to pool")
            elif container:
                await self._cleanup_container(container.container_id)
                logger.info(
                    f"[exec:{execution_id}] Destroyed container {container.container_id[:12]} (no release)"
                )

    async def _get_execution(self, execution_id: uuid.UUID) -> Execution:
        result = await self.db.execute(select(Execution).where(Execution.id == execution_id))
        execution = result.scalar_one_or_none()
        if not execution:
            raise ValueError(f"Execution not found: {execution_id}")
        return execution

    async def _get_run(self, execution: Execution) -> AgentRun:
        result = await self.db.execute(select(AgentRun).where(AgentRun.id == execution.run_id))
        run = result.scalar_one_or_none()
        if not run:
            raise ValueError(f"AgentRun not found for execution: {execution.id}")
        return run

    async def _get_release(self, run: AgentRun) -> AgentRelease:
        result = await self.db.execute(select(AgentRelease).where(AgentRelease.id == run.release_id))
        release = result.scalar_one_or_none()
        if not release:
            raise ValueError(f"AgentRelease not found for run: {run.id}")
        return release

    async def _get_auto_approve(self, execution: Execution, run: AgentRun) -> bool:
        if not run.task_id:
            return True
        result = await self.db.execute(select(Task.auto_approve).where(Task.id == run.task_id))
        val = result.scalar_one_or_none()
        return val if val is not None else True

    async def _mark_status(
        self,
        execution_id: uuid.UUID,
        status: str,
        container_id: Optional[str] = None,
        session_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        result_summary: Optional[dict[str, Any]] = None,
    ) -> None:
        """Update execution status directly on the model."""
        from app.utils.datetime import utc_now

        result = await self.db.execute(
            select(Execution).where(Execution.id == execution_id).with_for_update()
        )
        execution = result.scalar_one_or_none()
        if not execution:
            return

        now = utc_now()
        execution.status = status
        if error_code is not None:
            execution.error_code = error_code
        if error_message is not None:
            execution.error_message = error_message
        if container_id is not None:
            execution.runtime_session_ref = container_id
        if session_id is not None:
            execution.runtime_session_ref = session_id
        if result_summary is not None:
            execution.metrics = result_summary

        if status == "running" and not execution.started_at:
            execution.started_at = now
        if status in ("succeeded", "failed", "cancelled"):
            execution.ended_at = now

        await self.db.commit()

        from app.websocket.execution_subscription_manager import execution_subscription_manager
        await execution_subscription_manager.broadcast_event(
            str(execution_id),
            {"type": "execution_status", "execution_id": str(execution_id), "status": status},
        )

    async def _inject(
        self,
        *,
        container_id: str,
        skills: Optional[list[dict[str, Any]]],
        release: AgentRelease,
        working_dir: str,
    ) -> None:
        skill_injector = CLISkillInjector(self.container_service)
        config_injector = RuntimeConfigInjector(self.container_service)

        if skills:
            await skill_injector.inject(container_id, skills)

        # Pull instructions from release runtime_binding if present
        instructions = release.runtime_binding.get("instructions") if release else None
        skill_names = None
        if skills:
            skill_names = [s.get("name", "") for s in skills if s.get("name")]

        await config_injector.inject(
            container_id,
            instructions=instructions,
            skill_names=skill_names,
            working_dir=working_dir,
        )

    _DRAIN_BATCH_SIZE = 5
    _DRAIN_FLUSH_INTERVAL = 0.5  # seconds — flush at least every 500ms

    async def _drain_to_events(
        self,
        execution_id: uuid.UUID,
    ) -> None:
        assert self._session is not None, "_drain_to_events called before session was set"
        pending: list[tuple[CLIMessage, str, dict[str, Any]]] = []
        logger.info(f"[exec:{execution_id}] _drain_to_events started")
        queue = self._session.messages

        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=self._DRAIN_FLUSH_INTERVAL)
            except asyncio.TimeoutError:
                # Timeout — flush whatever we have so far
                if pending:
                    await self._flush_pending(execution_id, pending)
                    pending.clear()
                continue

            if msg is None:
                break

            event_type = self._msg_to_event_type(msg)
            payload = self._msg_to_payload(msg)
            pending.append((msg, event_type, payload))

            needs_flush = len(pending) >= self._DRAIN_BATCH_SIZE or msg.type == "approval_request"
            if needs_flush:
                await self._flush_pending(execution_id, pending)
                pending.clear()

        if pending:
            await self._flush_pending(execution_id, pending)
        logger.info(f"[exec:{execution_id}] _drain_to_events finished")

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
                        assert self._session is not None
                        await self._session.inject_message(build_control_response(request_id, "allow"))
                        await self.execution_service.append_event(
                            execution_id=execution_id,
                            event_type="approval_resolved",
                            payload={"decision": "auto_approved", "request_id": request_id},
                        )
                    else:
                        await self._mark_status(execution_id, "approval_wait")
                    break
        except Exception as exc:
            logger.warning(f"Failed to flush {len(pending)} events for {execution_id}: {exc}")

    async def _finalize(
        self,
        execution_id: uuid.UUID,
        result: CLIResult,
        release: AgentRelease,
    ) -> None:
        status = "succeeded" if result.status == "completed" else "failed"

        await self.execution_service.append_event(
            execution_id=execution_id,
            event_type="execution_completed" if status == "succeeded" else "error",
            payload={
                "result_summary": {"output_length": len(result.output)},
                "message": result.error or "",
            },
        )

        await self._mark_status(
            execution_id,
            status,
            session_id=result.session_id,
            error_message=result.error if result.error else None,
            result_summary=result.usage,
        )

        if self.callbacks:
            try:
                await self.callbacks.on_execution_finalized(execution_id, status, result)
            except Exception as exc:
                logger.warning(f"Callback on_execution_finalized failed for {execution_id}: {exc}")

    async def _mark_failed(
        self,
        execution_id: uuid.UUID,
        error: str,
    ) -> None:
        try:
            await self.execution_service.append_event(
                execution_id=execution_id,
                event_type="error",
                payload={"message": error},
            )
            await self._mark_status(execution_id, "failed", error_message=error[:2000])
        except Exception as exc:
            logger.error(f"Failed to mark execution {execution_id} as failed: {exc}")

        if self.callbacks:
            try:
                await self.callbacks.on_execution_failed(execution_id, error)
            except Exception as exc:
                logger.warning(f"Callback on_execution_failed failed for {execution_id}: {exc}")

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
