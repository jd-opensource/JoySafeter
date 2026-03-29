"""Graph Code API — save and run user LangGraph code.

Routes are nested under ``/api/v1/graphs`` and add code-specific
operations as sub-resources of an existing graph:

- ``POST /api/v1/graphs/{graph_id}/code/save``  — persist code
- ``POST /api/v1/graphs/{graph_id}/code/run``   — execute code and return result
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import NotFoundException
from app.core.code_executor import execute_code
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.models.graph import AgentGraph

router = APIRouter(prefix="/v1/graphs", tags=["Graph Code"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CodeSaveRequest(BaseModel):
    code: str = Field(..., description="Python code to save")
    name: Optional[str] = Field(default=None, description="Optional graph name update")


class CodeRunRequest(BaseModel):
    input: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Initial state input for the graph (e.g. {\"messages\": [...]})",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{graph_id}/code/save")
async def save_code(
    graph_id: uuid.UUID,
    payload: CodeSaveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist user code to ``graph.variables``.

    Sets ``graph_mode = "dsl"`` and stores the code string.
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
        f"[GraphCodeAPI] Saved code | graph_id={graph_id} | "
        f"code_len={len(payload.code)} | user={current_user.id}"
    )
    return {"success": True}


@router.post("/{graph_id}/code/run")
async def run_code(
    graph_id: uuid.UUID,
    payload: CodeRunRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute user code: exec → StateGraph → compile → invoke.

    Returns the final state after graph execution.
    """
    graph = await db.get(AgentGraph, graph_id)
    if not graph:
        raise NotFoundException(f"Graph {graph_id} not found")

    code = (graph.variables or {}).get("dsl_code", "")
    if not code.strip():
        return {
            "success": False,
            "message": "No code to execute. Save your code first.",
        }

    try:
        # Step 1: exec user code → get StateGraph
        state_graph = execute_code(code)

        # Step 2: compile
        compiled = state_graph.compile()

        # Step 3: invoke with user input
        initial_state = payload.input or {}
        result = await compiled.ainvoke(initial_state)

        logger.info(f"[GraphCodeAPI] Code run success | graph_id={graph_id}")
        return {
            "success": True,
            "data": {
                "result": _serialize_result(result),
            },
        }

    except SyntaxError as e:
        return {
            "success": False,
            "message": f"Syntax error at line {e.lineno}: {e.msg}",
        }
    except ImportError as e:
        return {
            "success": False,
            "message": str(e),
        }
    except ValueError as e:
        return {
            "success": False,
            "message": str(e),
        }
    except Exception as e:
        logger.error(f"[GraphCodeAPI] Code run failed | graph_id={graph_id} | error={e}")
        return {
            "success": False,
            "message": f"Runtime error: {type(e).__name__}: {e}",
        }


def _serialize_result(result: Any) -> Any:
    """Best-effort serialization of graph execution result."""
    if result is None:
        return None
    if isinstance(result, dict):
        return {k: _serialize_result(v) for k, v in result.items()}
    if isinstance(result, (list, tuple)):
        return [_serialize_result(item) for item in result]
    if isinstance(result, (str, int, float, bool)):
        return result
    # Fallback: try str()
    try:
        return str(result)
    except Exception:
        return f"<{type(result).__name__}>"
