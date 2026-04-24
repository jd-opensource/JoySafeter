"""
Copilot Execution Engine — routes copilot events through the unified event bus.

runtime_kind: "copilot"
Wraps CopilotService streaming and maps copilot events to ExecutionEvents
for persistence and WebSocket broadcast.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import ExecutionContext


class CopilotEngine:
    """Copilot engine — persists copilot events as ExecutionEvents."""

    engine_kind = "copilot"

    def __init__(self) -> None:
        self._running: dict[uuid.UUID, asyncio.Event] = {}

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        definition_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        """Stream copilot events, mapping each to an ExecutionEvent."""

        execution_id = context.execution_id

        graph_context = definition_payload.get("graph_context", {})
        conversation_history = definition_payload.get("conversation_history")
        mode = definition_payload.get("mode", "deepagents")
        provider_name = definition_payload.get("provider_name")
        model_name = definition_payload.get("model_name")
        user_id = definition_payload.get("user_id")

        logger.info(f"[CopilotEngine] Starting execution {execution_id} mode={mode}")

        cancel_event = asyncio.Event()
        self._running[execution_id] = cancel_event

        try:
            await context.update_status("running")
            await context.emit("execution_started", {"engine": "copilot", "mode": mode})

            from app.services.copilot_service import CopilotService

            service = CopilotService(
                user_id=user_id,
                provider_name=provider_name,
                model_name=model_name,
                db=context.db,
            )

            result_message = ""
            result_actions: list[dict] = []

            async for event in service.get_copilot_stream(
                prompt=prompt,
                graph_context=graph_context,
                conversation_history=conversation_history,
                mode=mode,
                graph_id=definition_payload.get("graph_id"),
            ):
                if cancel_event.is_set():
                    await context.complete("cancelled", "Cancelled by user")
                    return

                event_type = event.get("type", "")

                if event_type == "status":
                    await context.emit("copilot_status", {
                        "stage": event.get("stage"),
                        "message": event.get("message"),
                    })

                elif event_type == "content":
                    await context.emit("copilot_content", {
                        "content": event.get("content", ""),
                    })

                elif event_type == "thought_step":
                    await context.emit("copilot_thought_step", {
                        "step": event.get("step", {}),
                    })

                elif event_type == "tool_call":
                    await context.emit("copilot_tool_call", {
                        "tool": event.get("tool"),
                        "input": event.get("input", {}),
                    })

                elif event_type == "tool_result":
                    action = event.get("action", {})
                    result_actions.append(action)
                    await context.emit("copilot_tool_result", {
                        "action": action,
                    })

                elif event_type == "result":
                    result_message = event.get("message", "")
                    actions = event.get("actions", [])
                    result_actions = actions if actions else result_actions
                    await context.emit("copilot_result", {
                        "message": result_message,
                        "actions": result_actions,
                    })

                elif event_type == "error":
                    await context.emit("error", {
                        "message": event.get("message", "Unknown error"),
                        "code": event.get("code"),
                    })

                elif event_type == "done":
                    pass  # handled by complete() below

            await context.complete(
                "succeeded",
                result_message[:2000] if result_message else None,
            )

        except Exception as exc:
            logger.error(f"[CopilotEngine] Execution {execution_id} failed: {exc}")
            await context.emit("error", {"message": str(exc)})
            await context.complete("failed", str(exc)[:2000])
        finally:
            self._running.pop(execution_id, None)

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running copilot execution."""
        event = self._running.get(execution_id)
        if event:
            event.set()
            logger.info(f"[CopilotEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Copilot executions don't support message injection."""
        raise NotImplementedError("Message injection is not supported for copilot executions")
