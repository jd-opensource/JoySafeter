"""
LangGraph Code Execution Engine — sandboxed user-code executor.

engine_kind: "langgraph_code"
Extracts a StateGraph from user Python code via execute_code(),
compiles it, and executes it with streaming events.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.joysafeter_shared.common.app_errors import InternalServiceError, InvalidRequestError, normalize_app_error
from app.joysafeter_domain.engine.protocol import EngineCapabilities, ExecutionContext
from app.joysafeter_worker.events.event_types import ExecutionEventType


class LangGraphCodeEngine:
    """Sandboxed code executor engine."""

    engine_kind = "langgraph_code"
    capabilities = EngineCapabilities(
        supports_cancel=True,
        supports_message_injection=False,
        supports_debug_observation=True,
        supports_artifacts=False,
        supports_approval=False,
    )

    def __init__(self) -> None:
        self._running: dict[uuid.UUID, Any] = {}

    async def start(
        self,
        context: ExecutionContext,
        *,
        release_runtime_binding: dict[str, Any],
        engine_kind: str,
        definition_payload: dict[str, Any],
        prompt: str,
    ) -> None:
        """Extract StateGraph from user code, compile, and execute."""

        execution_id = context.execution_id

        if engine_kind != "langgraph_code":
            error = InvalidRequestError(
                f"LangGraphCodeEngine cannot handle engine_kind={engine_kind}",
                code="LANGGRAPH_CODE_ENGINE_KIND_MISMATCH",
                data={"engine_kind": engine_kind},
            )
            await context.complete("failed", error.message, error)
            return

        code = definition_payload.get("code", "")
        if not code or not code.strip():
            error = InvalidRequestError(
                "No code provided in definition_payload",
                code="CODE_DEFINITION_EMPTY",
            )
            await context.complete("failed", error.message, error)
            return

        logger.info(f"[LangGraphCodeEngine] Starting execution {execution_id} ({len(code)} chars of code)")

        cancel_event = asyncio.Event()
        self._running[execution_id] = cancel_event

        # ------------------------------------------------------------------
        # Observation: create root span + callback handler if collector set
        # ------------------------------------------------------------------
        root_span = None
        obs_handler = None
        if context.collector:
            root_span = context.collector.start_agent(name="code_executor")
            obs_handler = context.collector.create_langchain_handler()

        try:
            await context.update_status("running")
            await context.emit(
                ExecutionEventType.EXECUTION_STARTED,
                {
                    "engine": "langgraph_code",
                    "code_length": len(code),
                },
            )

            thread_id: str | None = None
            try:
                from app.joysafeter_domain.models.agent_run import AgentRun

                run = (
                    await context.db.execute(select(AgentRun).where(AgentRun.id == context.run_id))
                ).scalar_one_or_none()
                if run:
                    thread_id = str(run.thread_id) if run.thread_id else None
            except Exception as lookup_exc:
                logger.warning(f"[LangGraphCodeEngine] Could not resolve user_id/thread_id: {lookup_exc}")

            from app.joysafeter_domain.engine.code_executor import execute_code

            await context.emit(ExecutionEventType.ASSISTANT_TEXT, {"content": "Compiling user code..."})
            state_graph = execute_code(code)

            await context.emit(ExecutionEventType.ASSISTANT_TEXT, {"content": "Graph extracted, compiling..."})
            compiled = state_graph.compile()

            stream_config: dict[str, Any] = {
                "configurable": {"thread_id": thread_id or str(execution_id)},
            }
            if obs_handler:
                stream_config["callbacks"] = [obs_handler]

            result_text: str = ""
            async for chunk in compiled.astream(
                {"messages": [{"role": "user", "content": prompt}]},  # type: ignore[arg-type]
                stream_config,  # type: ignore[arg-type]
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
            logger.warning(f"[LangGraphCodeEngine] Code execution error {execution_id}: {exc}")
            app_error = normalize_app_error(
                exc,
                default_code="CODE_EXECUTION_INVALID",
                default_message="Code execution failed",
                default_data={"execution_id": str(execution_id)},
                source="engine",
            )
            await context.emit(ExecutionEventType.ERROR, app_error.to_payload())
            await context.complete("failed", app_error.message[:2000], app_error)
        except Exception as exc:
            logger.error(f"[LangGraphCodeEngine] Execution {execution_id} failed: {exc}")
            app_error = normalize_app_error(
                exc,
                default_code="CODE_EXECUTION_FAILED",
                default_message="Code execution failed",
                default_data={"execution_id": str(execution_id)},
                source="engine",
            )
            await context.emit(ExecutionEventType.ERROR, app_error.to_payload())
            await context.complete("failed", app_error.message[:2000], app_error)
        finally:
            self._running.pop(execution_id, None)
            if root_span:
                try:
                    root_span.set_output({"status": "completed"})
                    root_span.end()
                except Exception:
                    pass

    async def cancel(self, execution_id: uuid.UUID) -> None:
        event = self._running.get(execution_id)
        if event:
            event.set()
            logger.info(f"[LangGraphCodeEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        if execution_id not in self._running:
            raise InternalServiceError(
                "No running code execution",
                code="CODE_EXECUTION_NOT_RUNNING",
                data={"execution_id": str(execution_id)},
            )
        raise InvalidRequestError(
            code="CODE_EXECUTION_MESSAGE_UNSUPPORTED",
            message="Message injection is not supported for code executions",
            data={"execution_id": str(execution_id)},
        )
