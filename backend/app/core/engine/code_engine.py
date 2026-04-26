"""
Code Execution Engine — sandboxed user-code executor.

runtime_kind: "code"
Extracts a StateGraph from user Python code via execute_code(),
compiles it, and executes it with streaming events.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.core.engine.protocol import ExecutionContext
from app.core.events.event_types import ExecutionEventType


class CodeEngine:
    """Sandboxed code executor engine."""

    engine_kind = "code"

    def __init__(self) -> None:
        self._running: dict[uuid.UUID, Any] = {}

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        definition_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        """Extract StateGraph from user code, compile, and execute."""

        execution_id = context.execution_id

        if definition_kind != "code":
            await context.complete("failed", f"CodeEngine cannot handle definition_kind={definition_kind}")
            return

        code = definition_payload.get("code", "")
        if not code or not code.strip():
            await context.complete("failed", "No code provided in definition_payload")
            return

        logger.info(f"[CodeEngine] Starting execution {execution_id} ({len(code)} chars of code)")

        cancel_event = asyncio.Event()
        self._running[execution_id] = cancel_event

        try:
            await context.update_status("running")
            await context.emit(ExecutionEventType.EXECUTION_STARTED, {
                "engine": "code",
                "code_length": len(code),
            })

            user_id: str | None = None
            thread_id: str | None = None
            try:
                from app.models.agent_run import AgentRun
                run = (await context.db.execute(
                    select(AgentRun).where(AgentRun.id == context.run_id)
                )).scalar_one_or_none()
                if run:
                    user_id = run.created_by
                    thread_id = str(run.thread_id) if run.thread_id else None
            except Exception as lookup_exc:
                logger.warning(f"[CodeEngine] Could not resolve user_id/thread_id: {lookup_exc}")

            from app.core.code_executor import execute_code

            await context.emit(ExecutionEventType.ASSISTANT_TEXT, {"content": "Compiling user code..."})
            state_graph = execute_code(code)

            await context.emit(ExecutionEventType.ASSISTANT_TEXT, {"content": "Graph extracted, compiling..."})
            compiled = state_graph.compile()

            result_text: str = ""
            async for chunk in compiled.astream(
                {"messages": [{"role": "user", "content": prompt}]},
                {"configurable": {"thread_id": thread_id or str(execution_id)}},
            ):
                if cancel_event.is_set():
                    await context.complete("cancelled", "Execution cancelled by user")
                    return

                for node_output in chunk.values():
                    messages = node_output.get("messages", []) if isinstance(node_output, dict) else []
                    for msg in messages:
                        content = getattr(msg, "content", None) or (
                            msg.get("content") if isinstance(msg, dict) else None
                        )
                        if content:
                            result_text = str(content)
                            await context.emit(ExecutionEventType.ASSISTANT_TEXT, {"content": result_text})

            await context.complete("succeeded", result_text[:2000] if result_text else None)

        except (ValueError, ImportError, TimeoutError) as exc:
            logger.warning(f"[CodeEngine] Code execution error {execution_id}: {exc}")
            await context.emit(ExecutionEventType.ERROR, {"message": str(exc)})
            await context.complete("failed", str(exc)[:2000])
        except Exception as exc:
            logger.error(f"[CodeEngine] Execution {execution_id} failed: {exc}")
            await context.emit(ExecutionEventType.ERROR, {"message": str(exc)})
            await context.complete("failed", str(exc)[:2000])
        finally:
            self._running.pop(execution_id, None)

    async def cancel(self, execution_id: uuid.UUID) -> None:
        event = self._running.get(execution_id)
        if event:
            event.set()
            logger.info(f"[CodeEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        if execution_id not in self._running:
            raise RuntimeError(f"No running code execution for {execution_id}")
        raise NotImplementedError("Message injection is not supported for code executions")
