"""CLI Execution Engine — parameterized base for all CLI-based agent runtimes.

Covers: claude_code, codex, openclaw.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import EngineCapabilities, ExecutionContext
from app.core.events.event_types import ExecutionEventType


class CLIEngine:
    """CLI execution engine, parameterized by engine_kind."""

    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=True,
        supports_debug_observation=False,
        supports_artifacts=True,
        supports_approval=True,
    )

    def __init__(self, engine_kind: str) -> None:
        self.engine_kind = engine_kind

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        from app.core.database import AsyncSessionLocal

        execution_id = context.execution_id
        logger.info(f"[CLIEngine:{self.engine_kind}] Starting execution {execution_id}")

        await context.update_status("running")
        await context.emit(
            ExecutionEventType.EXECUTION_STARTED,
            {"engine": self.engine_kind},
        )

        async with AsyncSessionLocal() as db:
            runner = context.runner_factory(db)
            await runner.run(
                execution_id=execution_id,
                prompt=prompt,
                credentials=context.credentials or None,
                collector=context.collector,
            )

    async def cancel(self, execution_id: uuid.UUID) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.cancel()
            logger.info(f"[CLIEngine:{self.engine_kind}] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        from app.core.agent.cli_backends.session_registry import session_registry

        session = session_registry.get(execution_id)
        if session:
            await session.inject_message(message)
