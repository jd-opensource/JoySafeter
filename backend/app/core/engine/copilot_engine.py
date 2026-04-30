"""
Graph Builder Copilot Engine — internal platform engine.

engine_kind: "build_copilot"

This is NOT a user-facing agent runtime.  It is the AI assistant that helps
users design agent graphs on the visual canvas.  It reuses the execution
pipeline (Run → Execution → EventBus → WebSocket) for streaming and
persistence, but no user-created Agent ever has runtime_kind="build_copilot".

Wraps CopilotService streaming and maps copilot events to ExecutionEvents.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from loguru import logger

from app.common.app_errors import InternalServiceError, InvalidRequestError, normalize_app_error
from app.core.engine.protocol import EngineCapabilities, ExecutionContext
from app.core.events.event_types import ExecutionEventType


class CopilotEngine:
    """Graph Builder Copilot engine (internal) — persists copilot events as ExecutionEvents."""

    engine_kind = "build_copilot"
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=False,
        supports_debug_observation=False,
        supports_artifacts=False,
        supports_approval=False,
    )

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
            await context.emit(ExecutionEventType.EXECUTION_STARTED, {"engine": "build_copilot", "mode": mode})

            # ------------------------------------------------------------------
            # Observation: create copilot extractor if collector set
            # ------------------------------------------------------------------
            copilot_extractor = None
            obs_start: float = 0.0
            if context.collector and model_name:
                from app.core.observation.instrumentation.copilot_extractor import CopilotObservationExtractor

                copilot_extractor = CopilotObservationExtractor(context.collector, model_name)
                obs_start = time.monotonic()

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
                    await context.emit(
                        ExecutionEventType.COPILOT_STATUS,
                        {
                            "stage": event.get("stage"),
                            "message": event.get("message"),
                        },
                    )

                elif event_type == "content":
                    content_text = event.get("content", "")
                    await context.emit(
                        ExecutionEventType.COPILOT_CONTENT,
                        {
                            "content": content_text,
                        },
                    )
                    if copilot_extractor and content_text:
                        copilot_extractor.accumulate(content_text)

                elif event_type == "thought_step":
                    await context.emit(
                        ExecutionEventType.COPILOT_THOUGHT_STEP,
                        {
                            "step": event.get("step", {}),
                        },
                    )

                elif event_type == "tool_call":
                    await context.emit(
                        ExecutionEventType.COPILOT_TOOL_CALL,
                        {
                            "tool": event.get("tool"),
                            "input": event.get("input", {}),
                        },
                    )

                elif event_type == "tool_result":
                    action = event.get("action", {})
                    result_actions.append(action)
                    await context.emit(
                        ExecutionEventType.COPILOT_TOOL_RESULT,
                        {
                            "action": action,
                        },
                    )

                elif event_type == "result":
                    result_message = event.get("message", "")
                    actions = event.get("actions", [])
                    result_actions = actions if actions else result_actions
                    await context.emit(
                        ExecutionEventType.COPILOT_RESULT,
                        {
                            "message": result_message,
                            "actions": result_actions,
                        },
                    )

                elif event_type == "error":
                    code = event.get("code") or "COPILOT_EXECUTION_FAILED"
                    message = event.get("message", "Unknown error")
                    data = event.get("data")
                    source = event.get("source", "runtime")
                    retryable = event.get("retryable", False)
                    user_action = event.get("user_action")
                    await context.emit(
                        ExecutionEventType.ERROR,
                        {
                            "message": message,
                            "code": code,
                            "data": data,
                            "source": source,
                            "retryable": retryable,
                            **({"user_action": user_action} if user_action else {}),
                        },
                    )
                    app_error = InternalServiceError(
                        message=message,
                        code=code,
                        data=data if isinstance(data, dict) else None,
                        source=source,
                        retryable=bool(retryable),
                    )
                    await context.complete("failed", message[:2000], app_error)
                    return

                elif event_type == "done":
                    pass  # handled by complete() below

            # Observation: flush accumulated content
            if copilot_extractor:
                try:
                    elapsed_ms = (time.monotonic() - obs_start) * 1000
                    await copilot_extractor.flush(
                        prompt=prompt,
                        mode=mode,
                        elapsed_ms=elapsed_ms,
                    )
                except Exception as obs_exc:
                    logger.debug(f"[CopilotEngine] Observation flush error: {obs_exc}")

            await context.complete(
                "succeeded",
                result_message[:2000] if result_message else None,
            )

        except Exception as exc:
            logger.error(f"[CopilotEngine] Execution {execution_id} failed: {exc}")
            app_error = normalize_app_error(
                exc,
                default_code="COPILOT_EXECUTION_FAILED",
                default_message="Copilot execution failed",
                default_data={"execution_id": str(execution_id)},
                source="engine",
            )
            await context.emit(ExecutionEventType.ERROR, app_error.to_payload())
            await context.complete("failed", app_error.message[:2000], app_error)
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
        raise InvalidRequestError(
            "Message injection is not supported for copilot executions",
            code="COPILOT_EXECUTION_MESSAGE_UNSUPPORTED",
            data={"execution_id": str(execution_id)},
        )
