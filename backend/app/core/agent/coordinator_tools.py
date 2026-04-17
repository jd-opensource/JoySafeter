"""LangGraph tools for Coordinator agents to spawn and manage CLI agents."""
from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from loguru import logger

from app.core.agent.cli_backends.base import CLIResult
from app.core.agent.cli_backends.execution_runner import ExecutionRunner
from app.core.database import async_session_factory
from app.models.execution import ExecutionSource, MissionExecutionStatus
from app.services.execution_service import ExecutionService
from app.utils.safe_task import safe_create_task


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

    # Create child execution
    async with async_session_factory() as db:
        svc = ExecutionService(db)
        execution = await svc.create_execution(
            user_id=user_id,
            workspace_id=ws_id,
            source=ExecutionSource.COORDINATOR,
            runtime_type=runtime_type,
            title=f"[Sub] {agent_name}: {prompt[:80]}",
            parent_execution_id=parent_id,
        )
        exec_id = execution.id

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
            runner = ExecutionRunner(db)
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
            runner = ExecutionRunner(db)
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
        svc = ExecutionService(db)
        execution = await svc.get_execution(exec_id, user_id)

        if not execution:
            return {"status": "not_found", "output": ""}

        status = execution.status.value if hasattr(execution.status, "value") else str(execution.status)

        if status == MissionExecutionStatus.COMPLETED.value:
            output = ""
            if execution.result_summary:
                output = execution.result_summary.get("output", "")
            return {"status": "completed", "output": output}
        elif status == MissionExecutionStatus.FAILED.value:
            return {"status": "failed", "output": execution.error_message or "Unknown error"}
        else:
            return {"status": status, "output": f"Agent is still {status}"}
