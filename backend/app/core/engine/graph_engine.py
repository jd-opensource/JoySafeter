"""
Graph Execution Engine — wraps the existing LangGraph chat_turn_executor.

runtime_kind: "graph"
Compiles AgentVersion.definition_payload (nodes/edges) into a LangGraph StateGraph and executes it.
"""

from __future__ import annotations

import uuid
from typing import Any

from loguru import logger

from app.core.engine.protocol import ExecutionContext, ExecutionEngine


class GraphEngine:
    """LangGraph compiler + executor engine."""

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
        """Compile graph definition and execute via LangGraph."""

        execution_id = context.execution_id

        if definition_kind != "graph":
            await context.complete("failed", f"GraphEngine cannot handle definition_kind={definition_kind}")
            return

        nodes = definition_payload.get("nodes", [])
        edges = definition_payload.get("edges", [])
        variables = definition_payload.get("variables", {})

        if not nodes:
            await context.complete("failed", "Graph definition has no nodes")
            return

        logger.info(f"[GraphEngine] Starting execution {execution_id} with {len(nodes)} nodes")

        await context.update_status("running")
        await context.emit("execution_started", {
            "engine": "graph",
            "node_count": len(nodes),
            "edge_count": len(edges),
        })

        try:
            # Lazy import to avoid circular deps and heavy LangGraph import at module level
            from app.websocket.chat_turn_executor import ChatTurnExecutor
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                executor = ChatTurnExecutor(db)

                # The executor streams events — we bridge them to context.emit()
                async for event in executor.execute_graph(
                    nodes=nodes,
                    edges=edges,
                    variables=variables,
                    prompt=prompt,
                    credentials=context.credentials,
                    execution_id=execution_id,
                ):
                    event_type = event.get("type", "unknown")
                    await context.emit(event_type, event)

            await context.complete("succeeded")

        except Exception as exc:
            logger.error(f"[GraphEngine] Execution {execution_id} failed: {exc}")
            await context.complete("failed", str(exc)[:2000])

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running graph execution."""
        task = self._running.get(execution_id)
        if task:
            task.cancel()
            logger.info(f"[GraphEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Graph executions don't support message injection (yet)."""
        logger.warning(f"[GraphEngine] send_message not supported for {execution_id}")
