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

from app.core.engine.protocol import ExecutionContext, ExecutionEngine


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
            await context.complete("failed", f"GraphEngine cannot handle definition_kind={definition_kind}")
            return

        raw_nodes = definition_payload.get("nodes", [])
        raw_edges = definition_payload.get("edges", [])
        variables = definition_payload.get("variables", {}) or {}

        if not raw_nodes:
            await context.complete("failed", "Graph definition has no nodes")
            return

        logger.info(f"[GraphEngine] Starting execution {execution_id} with {len(raw_nodes)} nodes")

        cancel_event = asyncio.Event()
        self._running[execution_id] = cancel_event

        await context.update_status("running")
        await context.emit("execution_started", {
            "engine": "graph",
            "node_count": len(raw_nodes),
            "edge_count": len(raw_edges),
        })

        # ------------------------------------------------------------------
        # Resolve user_id and thread_id from the AgentRun linked to this
        # execution, so builder.py can initialise memory / sandbox correctly.
        # ------------------------------------------------------------------
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

        try:
            # ------------------------------------------------------------------
            # Build deep-agents graph
            # ------------------------------------------------------------------
            from app.core.graph.deep_agents.builder import build_deep_agents_graph

            compiled = await build_deep_agents_graph(
                graph,
                nodes,
                edges,
                user_id=user_id,
                model_service=None,  # resolved internally by ModelResolver
                thread_id=thread_id,
            )

            # ------------------------------------------------------------------
            # Run the compiled agent and stream events back through context
            # ------------------------------------------------------------------
            result_text: str = ""
            async for chunk in compiled.astream(
                {"messages": [{"role": "user", "content": prompt}]},
                {"configurable": {"thread_id": thread_id or str(execution_id)}},
            ):
                if cancel_event.is_set():
                    await context.complete("cancelled", "Execution cancelled by user")
                    return

                # deepagents yields dicts keyed by node name; extract text chunks
                for node_output in chunk.values():
                    messages = node_output.get("messages", []) if isinstance(node_output, dict) else []
                    for msg in messages:
                        content = getattr(msg, "content", None) or (
                            msg.get("content") if isinstance(msg, dict) else None
                        )
                        if content:
                            result_text = str(content)
                            await context.emit("agent_message", {"content": result_text})

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
            await context.complete("failed", str(exc)[:2000])
        finally:
            self._running.pop(execution_id, None)

    async def cancel(self, execution_id: uuid.UUID) -> None:
        """Cancel a running graph execution."""
        event = self._running.get(execution_id)
        if event:
            event.set()
            logger.info(f"[GraphEngine] Cancelled execution {execution_id}")

    async def send_message(self, execution_id: uuid.UUID, message: str) -> None:
        """Graph executions don't support message injection (yet)."""
        logger.warning(f"[GraphEngine] send_message not supported for {execution_id}")
