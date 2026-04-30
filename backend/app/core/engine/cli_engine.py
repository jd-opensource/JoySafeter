"""
CLI Execution Engine — wraps the existing ExecutionRunner for Docker + CLI agents.

runtime_kind: "sandbox"
Supports: Claude Code, Codex, OpenClaw
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import EngineCapabilities, ExecutionContext
from app.core.events.event_types import ExecutionEventType


class CLIEngine:
    """Docker container + CLI agent execution engine."""

    engine_kind = "sandbox"
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=True,
        supports_debug_observation=False,
        supports_artifacts=True,
        supports_approval=True,
    )

    def __init__(self) -> None:
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
        """Start a CLI agent execution in a Docker container.

        ExecutionRunner manages its own lifecycle: _finalize on success,
        _mark_failed on error. If runner.run() itself throws (extreme case),
        _fire_engine._run_engine provides the last-resort safety net.
        """
        from app.core.database import AsyncSessionLocal

        execution_id = context.execution_id
        runtime_type = release_runtime_binding.get("runtime_type", "claude_code")

        logger.info(f"[CLIEngine] Starting execution {execution_id} with {runtime_type}")

        await context.update_status("running")
        await context.emit(
            ExecutionEventType.EXECUTION_STARTED,
            {
                "engine": "cli",
                "runtime_type": runtime_type,
            },
        )

        async with AsyncSessionLocal() as db:
            from app.services.runner_factory import create_execution_runner

            runner = create_execution_runner(db)
            await runner.run(
                execution_id=execution_id,
                prompt=prompt,
                credentials=context.credentials or None,
                collector=context.collector,
            )

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running CLI execution."""
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.cancel()
            logger.info(f"[CLIEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Inject a message into a running CLI execution."""
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.inject_message(message)
