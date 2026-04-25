"""
CLI Execution Engine — wraps the existing ExecutionRunner for Docker + CLI agents.

runtime_kind: "sandbox"
Supports: Claude Code, Codex, OpenClaw
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import ExecutionContext, ExecutionEngine


class CLIEngine:
    """Docker container + CLI agent execution engine."""

    engine_kind = "sandbox"

    def __init__(self) -> None:
        # Track running sessions for cancel/message injection
        self._sessions: dict[uuid.UUID, Any] = {}

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        definition_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        """Start a CLI agent execution in a Docker container."""
        from app.core.agent.cli_backends.execution_runner import ExecutionRunner
        from app.core.database import AsyncSessionLocal

        execution_id = context.execution_id
        runtime_type = release_runtime_binding.get("runtime_type", "claude_code")

        logger.info(f"[CLIEngine] Starting execution {execution_id} with {runtime_type}")

        await context.update_status("running")
        await context.emit("execution_started", {
            "engine": "cli",
            "runtime_type": runtime_type,
        })

        try:
            async with AsyncSessionLocal() as db:
                runner = ExecutionRunner(db)
                result = await runner.run(
                    execution_id=execution_id,
                    prompt=prompt,
                    credentials=context.credentials or None,
                )

            # Map CLI result to execution status
            if result.status == "completed":
                await context.complete("succeeded", result.output[:2000] if result.output else None)
            elif result.status == "failed":
                await context.complete("failed", result.error[:2000] if result.error else None)
            elif result.status == "timeout":
                await context.complete("failed", "Execution timed out")
            else:
                await context.complete("failed", f"Unexpected result status: {result.status}")

        except asyncio.CancelledError:
            await context.complete("cancelled")
            raise
        except Exception as exc:
            logger.error(f"[CLIEngine] Execution {execution_id} failed: {exc}")
            await context.complete("failed", str(exc)[:2000])

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running CLI execution."""
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(str(execution_id))
        if session:
            await session.cancel()
            logger.info(f"[CLIEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Inject a message into a running CLI execution."""
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(str(execution_id))
        if session:
            await session.inject_message(message)
