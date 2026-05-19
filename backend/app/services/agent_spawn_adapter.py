"""AgentSpawnAdapter — implements AgentSpawnPort for coordinator sub-agent dispatch."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.cli_backends.base import CLIResult
from app.core.constants import RunPurpose, TriggerMedium
from app.core.ports.agent_spawn import AgentSpawnPort
from app.models.agent_run import AgentRun
from app.models.execution import Execution
from app.services.execution_orchestrator import ExecutionOrchestrator
from app.utils.safe_task import safe_create_task

EXECUTION_STATUS_COMPLETED = "succeeded"
EXECUTION_STATUS_FAILED = "failed"


class AgentSpawnAdapter:
    """Implements AgentSpawnPort — manages sub-agent lifecycle through orchestrator + runner."""

    def __init__(self, db_factory: Any) -> None:
        self._db_factory = db_factory

    async def spawn_and_wait(
        self,
        *,
        agent_name: str,
        prompt: str,
        workspace_id: str,
        user_id: str,
        parent_execution_id: str,
        runtime_type: str = "claude_code",
        model: str | None = None,
        timeout: int = 3600,
    ) -> dict:
        child = await self._create_child_execution(
            agent_name=agent_name,
            prompt=prompt,
            workspace_id=workspace_id,
            user_id=user_id,
            parent_execution_id=parent_execution_id,
            runtime_type=runtime_type,
        )
        logger.info(f"Coordinator spawned {agent_name} ({runtime_type}) -> execution {child.exec_id}")

        try:
            async with self._db_factory() as db:
                from app.services.runner_factory import create_execution_runner

                runner = create_execution_runner(db)
                collector = await self._create_collector(child)
                try:
                    result: CLIResult = await asyncio.wait_for(
                        runner.run(
                            execution_id=child.exec_id,
                            prompt=prompt,
                            model=model,
                            timeout=timeout,
                            collector=collector,
                        ),
                        timeout=timeout,
                    )
                finally:
                    if collector:
                        await collector.finalize()
            return {
                "execution_id": str(child.exec_id),
                "status": result.status,
                "output": result.output[:5000],
                "session_id": result.session_id,
            }
        except asyncio.TimeoutError:
            return {
                "execution_id": str(child.exec_id),
                "status": "timeout",
                "output": f"Agent '{agent_name}' timed out after {timeout}s",
            }
        except Exception as e:
            logger.error(f"spawn_agent error for {child.exec_id}: {e}")
            return {"execution_id": str(child.exec_id), "status": "failed", "output": str(e)[:2000]}

    async def spawn_fire_and_forget(
        self,
        *,
        agent_name: str,
        prompt: str,
        workspace_id: str,
        user_id: str,
        parent_execution_id: str,
        runtime_type: str = "claude_code",
        model: str | None = None,
    ) -> dict:
        child = await self._create_child_execution(
            agent_name=agent_name,
            prompt=prompt,
            workspace_id=workspace_id,
            user_id=user_id,
            parent_execution_id=parent_execution_id,
            runtime_type=runtime_type,
        )
        logger.info(f"Coordinator spawned {agent_name} ({runtime_type}) -> execution {child.exec_id} (fire-and-forget)")

        async def _background() -> None:
            async with self._db_factory() as db:
                from app.services.runner_factory import create_execution_runner

                runner = create_execution_runner(db)
                collector = await self._create_collector(child)
                try:
                    await runner.run(execution_id=child.exec_id, prompt=prompt, model=model, collector=collector)
                finally:
                    if collector:
                        await collector.finalize()

        safe_create_task(_background(), name=f"coordinator-child-{child.exec_id}")
        return {"execution_id": str(child.exec_id), "status": "dispatched", "output": ""}

    async def get_result(self, execution_id: str, *, user_id: str) -> dict:
        exec_id = uuid.UUID(execution_id)
        async with self._db_factory() as db:
            from app.services.execution_service import ExecutionService

            svc = ExecutionService(db)
            execution = await svc.get_execution(exec_id, user_id)

            if not execution:
                return {"status": "not_found", "output": ""}

            status = execution.status.value if hasattr(execution.status, "value") else str(execution.status)
            if status == EXECUTION_STATUS_COMPLETED:
                output = (execution.metrics or {}).get("output", "")
                return {"status": "succeeded", "output": output}
            elif status == EXECUTION_STATUS_FAILED:
                error = execution.error or {}
                return {"status": "failed", "output": error.get("message") or "Unknown error"}
            else:
                return {"status": status, "output": f"Agent is still {status}"}

    async def _create_child_execution(
        self,
        *,
        agent_name: str,
        prompt: str,
        workspace_id: str,
        user_id: str,
        parent_execution_id: str,
        runtime_type: str,
    ) -> _ChildExecution:
        ws_id = uuid.UUID(workspace_id)
        parent_id = uuid.UUID(parent_execution_id)

        async with self._db_factory() as db:
            from app.models.agent import AgentRelease

            parent_identity = (
                await db.execute(
                    select(AgentRun.release_id, AgentRun.agent_version_id, AgentRun.thread_id)
                    .join(Execution, AgentRun.id == Execution.run_id)
                    .where(Execution.id == parent_id)
                )
            ).one_or_none()
            if not parent_identity:
                raise ValueError(f"Parent execution {parent_id} not found")

            parent_release_id = parent_identity[0]
            parent_version_id = parent_identity[1]
            parent_thread_id = parent_identity[2]

            # Resolve agent_version_id: from AgentRun directly, or via release
            if parent_version_id:
                version_id = parent_version_id
            elif parent_release_id:
                release = (
                    await db.execute(select(AgentRelease).where(AgentRelease.id == parent_release_id))
                ).scalar_one()
                version_id = release.agent_version_id
            else:
                raise ValueError(f"Parent execution {parent_id} has neither release_id nor agent_version_id")

            run = AgentRun(
                release_id=parent_release_id,
                agent_version_id=None if parent_release_id else parent_version_id,
                workspace_id=ws_id,
                thread_id=parent_thread_id,
                trigger_medium=TriggerMedium.SYSTEM,
                run_purpose=RunPurpose.PRODUCTION,
                goal=f"[Sub] {agent_name}: {prompt[:80]}",
                status="pending",
                created_by=user_id,
            )
            db.add(run)
            await db.flush()

            from app.services.execution_service import ExecutionService

            svc = ExecutionService(db)
            execution = await svc.create_execution(
                run_id=run.id,
                runtime_type=runtime_type,
                parent_execution_id=parent_id,
            )
            run.current_execution_id = execution.id
            await db.commit()

            # Insert Trace row so observations FK correctly
            from app.core.observation.model import Trace
            from app.utils.datetime import utc_now

            trace = Trace(
                id=execution.id,
                name=f"[Sub] {agent_name}",
                workspace_id=ws_id,
                start_time=utc_now(),
                status="running",
                execution_id=execution.id,
                agent_version_id=version_id,
                user_id=uuid.UUID(user_id),
                session_id=str(parent_thread_id) if parent_thread_id else None,
                input={"prompt": prompt},
            )
            db.add(trace)
            await db.flush()
            await db.commit()

            await ExecutionOrchestrator.publish_run_status_change(
                db, run, execution_id=execution.id, target_status="running",
            )

            return _ChildExecution(
                exec_id=execution.id,
                workspace_id=ws_id,
                agent_name=agent_name,
            )

    async def _create_collector(self, child: _ChildExecution) -> Any:
        """Create an ObservationCollector for a child execution."""
        try:
            from app.core.database import AsyncSessionLocal
            from app.core.observation import ObservationCollector

            async def _db_factory():
                return AsyncSessionLocal()

            return ObservationCollector(
                trace_id=child.exec_id,
                execution_id=child.exec_id,
                workspace_id=child.workspace_id,
                db_session_factory=_db_factory,
            )
        except Exception:
            logger.opt(exception=True).warning(f"Failed to create ObservationCollector for child {child.exec_id}")
            return None


class _ChildExecution:
    __slots__ = ("exec_id", "workspace_id", "agent_name")

    def __init__(self, exec_id: uuid.UUID, workspace_id: uuid.UUID, agent_name: str) -> None:
        self.exec_id = exec_id
        self.workspace_id = workspace_id
        self.agent_name = agent_name
