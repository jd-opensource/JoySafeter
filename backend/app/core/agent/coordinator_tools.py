"""LangGraph tools for Coordinator agents to spawn and manage CLI agents."""

from __future__ import annotations

import asyncio
import uuid

from loguru import logger
from sqlalchemy import select

from app.core.agent.cli_backends.base import CLIResult
from app.core.database import async_session_factory
from app.services.execution_orchestrator import ExecutionOrchestrator
from app.models.execution import Execution
from app.utils.safe_task import safe_create_task

# Execution status string literals
EXECUTION_STATUS_COMPLETED = "succeeded"
EXECUTION_STATUS_FAILED = "failed"


async def spawn_agent(
    agent_name: str,
    prompt: str,
    *,
    workspace_id: str,
    user_id: str,
    parent_execution_id: str,
    runtime_type: str = "claude_code",
    model: str | None = None,
    wait: bool = True,
    timeout: int = 3600,
) -> dict:
    """
    Spawn a CLI agent to execute a sub-task.

    Args:
        agent_name: Display name for the spawned agent
        prompt: Task description for the agent
        workspace_id: Workspace context
        user_id: User who initiated the parent execution
        parent_execution_id: The coordinator's execution ID
        runtime_type: CLI type ("claude_code", "codex", "openclaw")
        model: Optional model override
        wait: If True, wait for completion and return result
        timeout: Max wait time in seconds

    Returns:
        dict with execution_id, status, and output (if wait=True)
    """
    ws_id = uuid.UUID(workspace_id)
    parent_id = uuid.UUID(parent_execution_id)

    async with async_session_factory() as db:
        from app.models.agent_run import AgentRun

        parent_identity = (
            await db.execute(
                select(AgentRun.release_id, AgentRun.agent_version_id)
                .join(Execution, AgentRun.id == Execution.run_id)
                .where(Execution.id == parent_id)
            )
        ).one_or_none()
        if not parent_identity:
            raise ValueError(f"Parent execution {parent_id} not found")

        parent_release = parent_identity[0]
        parent_version = None if parent_release else parent_identity[1]

        run = AgentRun(
            release_id=parent_release,
            agent_version_id=parent_version,
            workspace_id=ws_id,
            trigger_medium="system",
            run_purpose="production",
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
        exec_id = execution.id

        await ExecutionOrchestrator.publish_run_status_change(
            db,
            run,
            execution_id=execution.id,
            target_status="running",
        )

    logger.info(f"Coordinator spawned {agent_name} ({runtime_type}) -> execution {exec_id}")

    if wait:
        return await _run_and_wait(exec_id, prompt, ws_id, user_id, runtime_type, model, timeout, agent_name)
    else:
        _fire_and_forget(exec_id, prompt, ws_id, user_id, runtime_type, model)
        return {
            "execution_id": str(exec_id),
            "status": "dispatched",
            "output": "",
        }


async def _run_and_wait(
    exec_id: uuid.UUID,
    prompt: str,
    ws_id: uuid.UUID,
    user_id: str,
    runtime_type: str,
    model: str | None,
    timeout: int,
    agent_name: str,
) -> dict:
    """Run the execution synchronously and return the result."""
    try:
        async with async_session_factory() as db:
            from app.services.runner_factory import create_execution_runner

            runner = create_execution_runner(db)
            result: CLIResult = await asyncio.wait_for(
                runner.run(
                    execution_id=exec_id,
                    prompt=prompt,
                    model=model,
                    timeout=timeout,
                ),
                timeout=timeout,
            )
        return {
            "execution_id": str(exec_id),
            "status": result.status,
            "output": result.output[:5000],
            "session_id": result.session_id,
        }
    except asyncio.TimeoutError:
        return {
            "execution_id": str(exec_id),
            "status": "timeout",
            "output": f"Agent '{agent_name}' timed out after {timeout}s",
        }
    except Exception as e:
        logger.error(f"spawn_agent error for {exec_id}: {e}")
        return {
            "execution_id": str(exec_id),
            "status": "failed",
            "output": str(e)[:2000],
        }


def _fire_and_forget(
    exec_id: uuid.UUID,
    prompt: str,
    ws_id: uuid.UUID,
    user_id: str,
    runtime_type: str,
    model: str | None,
) -> None:
    """Dispatch execution as a background task."""

    async def _background():
        async with async_session_factory() as db:
            from app.services.runner_factory import create_execution_runner

            runner = create_execution_runner(db)
            await runner.run(execution_id=exec_id, prompt=prompt, model=model)

    safe_create_task(
        _background(),
        name=f"coordinator-child-{exec_id}",
    )


async def get_agent_result(execution_id: str, *, user_id: str) -> dict:
    """
    Get the result of a previously spawned agent.

    Args:
        execution_id: The execution ID returned by spawn_agent
        user_id: The user who owns the execution

    Returns:
        dict with status and output
    """
    exec_id = uuid.UUID(execution_id)

    async with async_session_factory() as db:
        from app.services.execution_service import ExecutionService

        svc = ExecutionService(db)
        execution = await svc.get_execution(exec_id, user_id)

        if not execution:
            return {"status": "not_found", "output": ""}

        status = execution.status.value if hasattr(execution.status, "value") else str(execution.status)

        if status == EXECUTION_STATUS_COMPLETED:
            output = ""
            if execution.metrics:
                output = execution.metrics.get("output", "")
            return {"status": "succeeded", "output": output}
        elif status == EXECUTION_STATUS_FAILED:
            error = execution.error or {}
            return {"status": "failed", "output": error.get("message") or "Unknown error"}
        else:
            return {"status": status, "output": f"Agent is still {status}"}
