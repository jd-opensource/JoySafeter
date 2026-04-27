"""
DispatchService — API layer's single entry point for execution dispatch.

Wraps ExecutionOrchestrator so that API routes never import from core/engine/.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.engine.orchestrator import ExecutionOrchestrator
from app.models.agent_run import AgentRun


class DispatchService:

    def __init__(self, db: AsyncSession):
        self._orchestrator = ExecutionOrchestrator(db)

    async def dispatch_task(
        self,
        task_id: uuid.UUID,
        user_id: str,
        prompt_override: str | None = None,
    ) -> AgentRun:
        return await self._orchestrator.dispatch_task(task_id, user_id, prompt_override)

    async def dispatch_chat(
        self,
        thread_id: uuid.UUID,
        message: str,
        user_id: str,
    ) -> AgentRun:
        return await self._orchestrator.dispatch_chat(thread_id, message, user_id)

    async def dispatch_direct(
        self,
        release_id: uuid.UUID,
        prompt: str,
        user_id: str,
        trigger_source: str = "api",
        thread_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        input_payload: dict | None = None,
    ) -> AgentRun:
        return await self._orchestrator.dispatch_direct(
            release_id, prompt, user_id,
            trigger_source=trigger_source,
            thread_id=thread_id,
            task_id=task_id,
            input_payload=input_payload,
        )

    async def dispatch_draft(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        prompt: str,
        user_id: str,
        workspace_id: uuid.UUID,
        input_payload: dict | None = None,
    ) -> AgentRun:
        return await self._orchestrator.dispatch_draft(
            agent_id, version_id, prompt, user_id, workspace_id,
            input_payload=input_payload,
        )

    async def dispatch_copilot(
        self,
        agent_id: uuid.UUID,
        prompt: str,
        user_id: str,
        graph_context: dict,
        conversation_history: list | None = None,
        mode: str = "deepagents",
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        return await self._orchestrator.dispatch_copilot(
            agent_id, prompt, user_id, graph_context,
            conversation_history=conversation_history,
            mode=mode,
            provider_name=provider_name,
            model_name=model_name,
        )

    async def dispatch_copilot_draft(
        self,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        workspace_id: uuid.UUID,
        prompt: str,
        user_id: str,
        graph_context: dict,
        conversation_history: list | None = None,
        mode: str = "deepagents",
        provider_name: str | None = None,
        model_name: str | None = None,
    ) -> AgentRun:
        return await self._orchestrator.dispatch_copilot_draft(
            agent_id=agent_id,
            version_id=version_id,
            workspace_id=workspace_id,
            prompt=prompt,
            user_id=user_id,
            graph_context=graph_context,
            conversation_history=conversation_history,
            mode=mode,
            provider_name=provider_name,
            model_name=model_name,
        )

    async def cancel_run(self, run_id: uuid.UUID) -> AgentRun:
        return await self._orchestrator.cancel_run(run_id)

    async def retry_run(self, run_id: uuid.UUID, user_id: str) -> AgentRun:
        return await self._orchestrator.retry_run(run_id, user_id)

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        return await self._orchestrator.send_message(execution_id, message)

    async def emit_user_message(
        self,
        *,
        run: AgentRun,
        execution_id: uuid.UUID,
        message: str,
        attachments: list[dict] | None = None,
    ) -> None:
        return await self._orchestrator.emit_user_message(
            run=run, execution_id=execution_id,
            message=message, attachments=attachments,
        )
