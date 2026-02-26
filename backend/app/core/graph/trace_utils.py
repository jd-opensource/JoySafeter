"""
Trace utilities for graph node execution observability.

Provides utilities to record node execution context, input/output snapshots,
and state history for debugging complex graphs.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional, cast

from langchain_core.runnables import RunnableConfig
from loguru import logger

from app.core.graph.graph_state import GraphState


class NodeExecutionTrace:
    """Trace record for a single node execution."""

    def __init__(
        self,
        node_id: str,
        node_type: str,
        start_time: float,
        input_snapshot: Optional[Dict[str, Any]] = None,
        output_snapshot: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ):
        self.node_id = node_id
        self.node_type = node_type
        self.start_time = start_time
        self.end_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
        self.input_snapshot = input_snapshot or {}
        self.output_snapshot = output_snapshot or {}
        self.error = error
        self.error_message: Optional[str] = None
        if error:
            self.error_message = str(error)

    def finish(self, end_time: float, output: Optional[Dict[str, Any]] = None):
        """Mark trace as finished and record output."""
        self.end_time = end_time
        self.duration_ms = (end_time - self.start_time) * 1000
        if output:
            self.output_snapshot = output

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to dictionary for logging/storage."""
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "input_snapshot": self._sanitize_snapshot(self.input_snapshot),
            "output_snapshot": self._sanitize_snapshot(self.output_snapshot),
            "error": self.error_message,
        }

    def _sanitize_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize snapshot to remove sensitive data and limit size."""
        sanitized: Dict[str, Any] = {}
        for key, value in snapshot.items():
            # Skip large messages lists (keep only count)
            if key == "messages" and isinstance(value, list):
                sanitized[key] = f"<{len(value)} messages>"
            # Limit string length
            elif isinstance(value, str) and len(value) > 500:
                sanitized[key] = value[:500] + "..."
            # Recursively sanitize dicts
            elif isinstance(value, dict):
                sanitized[key] = self._sanitize_snapshot(value)
            else:
                sanitized[key] = value
        return sanitized


class GraphExecutionTrace:
    """Trace for entire graph execution."""

    def __init__(self, graph_id: str, graph_name: str):
        self.graph_id = graph_id
        self.graph_name = graph_name
        self.start_time = datetime.now().isoformat()
        self.node_traces: List[NodeExecutionTrace] = []
        self.state_history: List[Dict[str, Any]] = []

    def add_node_trace(self, trace: NodeExecutionTrace):
        """Add a node execution trace."""
        self.node_traces.append(trace)

    def add_state_snapshot(self, state: GraphState, node_id: Optional[str] = None):
        """Add a state snapshot to history."""
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "node_id": node_id,
            "state": self._sanitize_state(state),
        }
        self.state_history.append(snapshot)

    def _sanitize_state(self, state: GraphState) -> Dict[str, Any]:
        """Create a sanitized snapshot of state."""
        return {
            "current_node": state.get("current_node"),
            "route_decision": state.get("route_decision"),
            "loop_count": state.get("loop_count"),
            "messages_count": len(cast(list, state.get("messages", []))),
            "context_keys": list(cast(dict, state.get("context", {})).keys()),
            "task_results_count": len(cast(list, state.get("task_results", []))),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert trace to dictionary."""
        return {
            "graph_id": self.graph_id,
            "graph_name": self.graph_name,
            "start_time": self.start_time,
            "node_traces": [trace.to_dict() for trace in self.node_traces],
            "state_history": self.state_history,
        }


def create_node_trace(
    node_id: str,
    node_type: str,
    state: GraphState,
    config: Optional[RunnableConfig] = None,
) -> NodeExecutionTrace:
    """Create a trace for node execution with input snapshot."""
    import time

    # Create input snapshot
    input_snapshot = {
        "current_node": state.get("current_node"),
        "route_decision": state.get("route_decision"),
        "loop_count": state.get("loop_count"),
        "messages_count": len(cast(list, state.get("messages", []))),
        "context_keys": list(cast(dict, state.get("context", {})).keys()),
    }

    trace = NodeExecutionTrace(
        node_id=node_id,
        node_type=node_type,
        start_time=time.time(),
        input_snapshot=input_snapshot,
    )

    if config:
        # Extract LangSmith/LangChain trace info
        if "configurable" in config:
            # Maybe store configurable?
            pass
        if "callbacks" in config:
            # Callbacks might contain trace info
            pass
        # run_id is usually available in get_run_tree_context if implicit,
        # or we might want to capture metadata from config['metadata']
        if "metadata" in config:
            trace.input_snapshot["_meta_trace"] = config["metadata"]

    return trace


def log_node_execution(
    trace: NodeExecutionTrace,
    node_id: str,
    node_type: str,
):
    """Log node execution trace."""
    if trace.error:
        logger.error(
            f"[Trace] Node execution failed | "
            f"node_id={node_id} | node_type={node_type} | "
            f"duration={trace.duration_ms:.2f}ms | error={trace.error_message}"
        )
    else:
        logger.info(
            f"[Trace] Node execution completed | "
            f"node_id={node_id} | node_type={node_type} | "
            f"duration={trace.duration_ms:.2f}ms"
        )
