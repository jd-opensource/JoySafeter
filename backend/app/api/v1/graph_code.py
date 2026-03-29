"""Graph Code API — DSL code parse and save endpoints.

Routes are nested under ``/api/v1/graphs`` and add code-specific
operations as sub-resources of an existing graph:

- ``POST /api/v1/graphs/{graph_id}/code/parse``  — stateless parse
- ``POST /api/v1/graphs/{graph_id}/code/save``   — persist DSL code
"""

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import NotFoundException
from app.core.database import get_db
from app.core.dsl.dsl_parser import DSLParser
from app.core.graph.graph_schema import GraphSchema
from app.models.auth import AuthUser as User
from app.models.graph import AgentGraph

router = APIRouter(prefix="/v1/graphs", tags=["Graph Code"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CodeParseRequest(BaseModel):
    code: str = Field(..., description="DSL Python code to parse")


class CodeSaveRequest(BaseModel):
    code: str = Field(..., description="DSL Python code to save")
    name: Optional[str] = Field(default=None, description="Optional graph name update")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _schema_to_preview(schema: GraphSchema) -> Dict[str, Any]:
    """Convert a GraphSchema to ReactFlow-ready preview data.

    Performs simple auto-layout: nodes placed in a vertical grid based
    on topological order.
    """
    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []

    # Simple grid layout
    x_start, y_start = 100, 100
    y_step = 150
    x_step = 300

    # Group nodes by layer (BFS from start nodes)
    node_ids = {n.id for n in schema.nodes}
    incoming: Dict[str, set] = {nid: set() for nid in node_ids}
    for e in schema.edges:
        if e.target in incoming:
            incoming[e.target].add(e.source)

    # Assign layers via topological sort
    layers: Dict[str, int] = {}
    queue = [nid for nid, inc in incoming.items() if not inc]
    layer = 0
    while queue:
        for nid in queue:
            layers[nid] = layer
        next_queue = []
        for e in schema.edges:
            if e.source in set(queue) and e.target not in layers:
                # Check if all incoming are resolved
                if all(s in layers for s in incoming[e.target]):
                    next_queue.append(e.target)
        queue = list(dict.fromkeys(next_queue))  # dedupe preserving order
        layer += 1

    # Assign remaining unconnected nodes
    for n in schema.nodes:
        if n.id not in layers:
            layers[n.id] = layer
            layer += 1

    # Count nodes per layer for x positioning
    layer_counts: Dict[int, int] = {}
    for n in schema.nodes:
        ly = layers.get(n.id, 0)
        idx = layer_counts.get(ly, 0)
        layer_counts[ly] = idx + 1

        nodes.append({
            "id": n.id,
            "type": "custom",
            "position": {"x": x_start + idx * x_step, "y": y_start + ly * y_step},
            "data": {
                "label": n.label,
                "type": n.type,
                "config": n.config,
            },
        })

    for e in schema.edges:
        edges.append({
            "id": f"{e.source}-{e.target}",
            "source": e.source,
            "target": e.target,
            "label": e.route_key or "",
            "type": "default",
        })

    return {"nodes": nodes, "edges": edges}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{graph_id}/code/parse")
async def parse_dsl_code(
    graph_id: uuid.UUID,
    payload: CodeParseRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stateless parse: DSL code → schema + preview + errors.

    Does not persist anything. Used by the frontend for real-time
    parse feedback as the user types.
    """
    parser = DSLParser()
    result = parser.parse(payload.code)

    schema = None
    preview = None
    if not any(e.severity == "error" for e in result.errors):
        try:
            schema = parser._build_schema(result)
            preview = _schema_to_preview(schema)
        except Exception as exc:
            logger.warning(f"[GraphCodeAPI] Schema build failed: {exc}")
            from app.core.dsl.dsl_models import ParseError as _PE

            result.errors.append(_PE(line=None, message=str(exc)))

    return {
        "success": True,
        "data": {
            "schema": schema.model_dump(mode="json") if schema else None,
            "preview": preview,
            "errors": [
                {"line": e.line, "message": e.message, "severity": e.severity}
                for e in result.errors
            ],
        },
    }


@router.post("/{graph_id}/code/save")
async def save_dsl_code(
    graph_id: uuid.UUID,
    payload: CodeSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist DSL code to ``graph.variables``.

    Sets ``graph_mode = "dsl"`` and stores the code string.
    Parse errors do NOT block saving — users can save broken code.
    """
    graph = await db.get(AgentGraph, graph_id)
    if not graph:
        raise NotFoundException(f"Graph {graph_id} not found")

    variables = dict(graph.variables or {})
    variables["graph_mode"] = "dsl"
    variables["dsl_code"] = payload.code
    graph.variables = variables

    if payload.name is not None:
        graph.name = payload.name

    await db.commit()

    logger.info(
        f"[GraphCodeAPI] Saved DSL code | graph_id={graph_id} | "
        f"code_len={len(payload.code)} | user={current_user.id}"
    )
    return {"success": True}
