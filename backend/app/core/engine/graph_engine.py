"""
Graph Execution Engine — DeepAgents-based executor.

runtime_kind: "graph"
Compiles AgentVersion.definition_payload (nodes/edges) into a DeepAgents graph and executes it.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.common.app_errors import InternalServiceError, InvalidRequestError, normalize_app_error
from app.core.engine.protocol import ExecutionContext
from app.core.events.event_types import ExecutionEventType

# ---------------------------------------------------------------------------
# Duck-typed shims — wrap plain dicts from definition_payload into objects
# that builder.py / config.py can consume without touching ORM models.
# ---------------------------------------------------------------------------


class _GraphShim:
    """Minimal graph-like object derived from execution context + payload."""

    def __init__(
        self,
        agent_id: Any,
        workspace_id: Any,
        variables: dict,
        name: str = "",
    ) -> None:
        self.id = agent_id
        self.workspace_id = workspace_id
        self.variables = variables
        self.name = name
        self.title = name


class _NodeShim:
    """Wraps a node dict from definition_payload['nodes'] into a duck-typed object."""

    def __init__(self, d: dict) -> None:
        self.id = d.get("id")
        self.type = d.get("type", "")
        self.data = d.get("data", {})


class _EdgeShim:
    """Wraps an edge dict from definition_payload['edges'] into a duck-typed object."""

    def __init__(self, d: dict) -> None:
        # Support both snake_case (internal) and camelCase / React-Flow key names
        self.source_node_id = d.get("source_node_id") or d.get("source")
        self.target_node_id = d.get("target_node_id") or d.get("target")


def _extract_message_contents_from_stream_chunk(chunk: Any) -> list[str]:
    """Extract assistant text from LangGraph update chunks.

    DeepAgents middleware can emit ``messages=Overwrite([...])`` to replace state.
    That is a state update, not a new assistant message, and it is not iterable.
    """
    if not isinstance(chunk, dict):
        return []

    contents: list[str] = []
    for node_output in chunk.values():
        if not isinstance(node_output, dict):
            continue

        messages = node_output.get("messages", [])
        for msg in _iter_stream_messages(messages):
            if not _is_assistant_message(msg):
                continue

            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
            if content:
                contents.append(str(content))

    return contents


def _iter_stream_messages(messages: Any) -> list[Any]:
    if _is_overwrite_update(messages):
        return []
    if isinstance(messages, list | tuple):
        return list(messages)
    if isinstance(messages, dict):
        return [messages] if "content" in messages else []
    if hasattr(messages, "content"):
        return [messages]
    return []


def _is_overwrite_update(value: Any) -> bool:
    if value.__class__.__name__ == "Overwrite" and hasattr(value, "value"):
        return True
    return isinstance(value, dict) and set(value.keys()) == {"__overwrite__"}


def _is_assistant_message(message: Any) -> bool:
    if isinstance(message, dict):
        role = message.get("role") or message.get("type")
        return role in {"assistant", "ai"}
    return getattr(message, "type", None) == "ai" or getattr(message, "role", None) == "assistant"


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class GraphEngine:
    """DeepAgents compiler + executor engine."""

    engine_kind = "graph"

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
        """Compile graph definition and execute via DeepAgents."""

        execution_id = context.execution_id

        if definition_kind != "graph":
            error = InvalidRequestError(
                f"GraphEngine cannot handle definition_kind={definition_kind}",
                code="GRAPH_DEFINITION_KIND_UNSUPPORTED",
                data={"definition_kind": definition_kind},
            )
            await context.complete("failed", error.message, error)
            return

        raw_nodes = definition_payload.get("nodes", [])
        raw_edges = definition_payload.get("edges", [])
        variables = definition_payload.get("variables", {}) or {}

        if not raw_nodes:
            error = InvalidRequestError(
                "Graph definition has no nodes",
                code="GRAPH_DEFINITION_NODES_EMPTY",
            )
            await context.complete("failed", error.message, error)
            return

        logger.info(f"[GraphEngine] Starting execution {execution_id} with {len(raw_nodes)} nodes")

        cancel_event = asyncio.Event()
        self._running[execution_id] = cancel_event

        await context.update_status("running")
        await context.emit(
            ExecutionEventType.EXECUTION_STARTED,
            {
                "engine": "graph",
                "node_count": len(raw_nodes),
                "edge_count": len(raw_edges),
            },
        )

        # ------------------------------------------------------------------
        # Resolve user_id and thread_id from the AgentRun linked to this
        # execution, so builder.py can initialise memory / sandbox correctly.
        # ------------------------------------------------------------------
        user_id: str | None = None
        thread_id: str | None = None
        try:
            from app.models.agent_run import AgentRun

            run = (await context.db.execute(select(AgentRun).where(AgentRun.id == context.run_id))).scalar_one_or_none()
            if run:
                user_id = run.created_by
                thread_id = str(run.thread_id) if run.thread_id else None
        except Exception as lookup_exc:  # pragma: no cover
            logger.warning(f"[GraphEngine] Could not resolve user_id/thread_id: {lookup_exc}")

        # ------------------------------------------------------------------
        # Wrap plain dicts into duck-typed shim objects
        # ------------------------------------------------------------------
        nodes = [_NodeShim(n) for n in raw_nodes]
        edges = [_EdgeShim(e) for e in raw_edges]
        graph = _GraphShim(
            agent_id=context.run_id,  # stable surrogate — run_id is graph-level unique here
            workspace_id=context.workspace_id,
            variables=variables,
            name=definition_payload.get("name", ""),
        )

        # ------------------------------------------------------------------
        # Observation: create root span + callback handler if collector set
        # ------------------------------------------------------------------
        root_span = None
        obs_handler = None
        if context.collector:
            from app.core.observation.instrumentation.langchain_handler import ObservationCallbackHandler

            graph_name = definition_payload.get("name", "graph")
            root_span = await context.collector.start_agent(name=f"root:{graph_name}")
            obs_handler = ObservationCallbackHandler(context.collector, root_span)

        try:
            # ------------------------------------------------------------------
            # Build deep-agents graph
            # ------------------------------------------------------------------
            from app.core.graph.deep_agents.builder import build_deep_agents_graph
            from app.services.model_service import ModelService

            model_service = ModelService(context.db)

            compiled = await build_deep_agents_graph(
                graph,
                nodes,
                edges,
                user_id=user_id,
                model_service=model_service,
                thread_id=thread_id,
            )

            # ------------------------------------------------------------------
            # Run the compiled agent and stream events back through context
            # ------------------------------------------------------------------
            stream_config: dict[str, Any] = {
                "configurable": {"thread_id": thread_id or str(execution_id)},
            }
            if obs_handler:
                stream_config["callbacks"] = [obs_handler]

            result_text: str = ""
            async for chunk in compiled.astream(
                {"messages": [{"role": "user", "content": prompt}]},
                stream_config,
            ):
                if cancel_event.is_set():
                    await context.complete("cancelled", "Execution cancelled by user")
                    return

                # deepagents yields dicts keyed by node name; extract text chunks
                for content in _extract_message_contents_from_stream_chunk(chunk):
                    result_text = content
                    await context.emit(ExecutionEventType.ASSISTANT_TEXT, {"content": result_text})

            # ------------------------------------------------------------------
            # Cleanup sandbox if the compiled agent holds one
            # ------------------------------------------------------------------
            sandbox_handle = getattr(compiled, "_sandbox_handle", None)
            if sandbox_handle:
                try:
                    await sandbox_handle.release()
                except Exception as cleanup_exc:  # pragma: no cover
                    logger.warning(f"[GraphEngine] Sandbox cleanup failed: {cleanup_exc}")

            await context.complete("succeeded", result_text[:2000] if result_text else None)

        except Exception as exc:
            logger.error(f"[GraphEngine] Execution {execution_id} failed: {exc}")
            app_error = normalize_app_error(
                exc,
                default_code="GRAPH_EXECUTION_FAILED",
                default_message="Graph execution failed",
                default_data={"execution_id": str(execution_id)},
            )
            await context.emit(ExecutionEventType.ERROR, app_error.to_payload())
            await context.complete("failed", app_error.message[:2000], app_error)
        finally:
            self._running.pop(execution_id, None)
            if root_span:
                try:
                    await root_span.end(output={"status": "completed"})
                except Exception:
                    pass

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running graph execution."""
        event = self._running.get(execution_id)
        if event:
            event.set()
            logger.info(f"[GraphEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Graph executions don't support message injection (yet)."""
        if execution_id not in self._running:
            raise InternalServiceError(
                "No running graph execution",
                code="GRAPH_EXECUTION_NOT_RUNNING",
                data={"execution_id": str(execution_id)},
            )
        raise InvalidRequestError(
            "Message injection is not yet supported for graph executions",
            code="GRAPH_EXECUTION_MESSAGE_UNSUPPORTED",
            data={"execution_id": str(execution_id)},
        )
