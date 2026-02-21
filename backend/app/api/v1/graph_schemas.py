"""
Graph Schema API — Schema export, import, validation, and code generation.

Routes are nested under ``/api/v1/graphs`` and add schema-specific
operations as sub-resources of an existing graph:

- ``GET  /api/v1/graphs/{graph_id}/schema``  — export graph as JSON schema
- ``GET  /api/v1/graphs/{graph_id}/schema/code``  — export as Python code
- ``GET  /api/v1/graphs/{graph_id}/schema/validate``  — validate graph schema
- ``POST /api/v1/graphs/schema/import``  — import schema JSON as a new graph
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.services.schema_service import SchemaService

router = APIRouter(prefix="/v1/graphs", tags=["Graph Schemas"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SchemaImportRequest(BaseModel):
    """Request body for importing a graph schema."""

    schema_data: Dict[str, Any] = Field(..., description="Serialized GraphSchema JSON")
    workspace_id: Optional[uuid.UUID] = Field(
        default=None, alias="workspaceId", description="Workspace to create the graph in"
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{graph_id}/schema")
async def export_graph_schema(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a graph as a ``GraphSchema`` JSON object.

    The returned schema is a complete, portable description of the graph
    that can be imported into another JoySafeter instance or used with
    the code generator.
    """
    service = SchemaService(db)
    schema = await service.export_schema(graph_id)
    return {
        "success": True,
        "data": schema.model_dump(mode="json"),
    }


@router.get("/{graph_id}/schema/code")
async def export_graph_code(
    graph_id: uuid.UUID,
    include_main: bool = Query(default=True, alias="includeMain"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Export a graph as standalone Python code.

    The generated code is a complete, runnable script that uses
    LangGraph to build and execute the graph — no JoySafeter
    dependency required.
    """
    service = SchemaService(db)
    code = await service.export_code(graph_id, include_main=include_main)
    return {
        "success": True,
        "data": {
            "code": code,
            "language": "python",
        },
    }


@router.get("/{graph_id}/schema/validate")
async def validate_graph_schema(
    graph_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate a graph schema and return diagnostics.

    Returns structural validation results including errors (that would
    prevent compilation) and warnings (that may indicate issues).
    """
    service = SchemaService(db)
    result = await service.validate_schema(graph_id)
    return {
        "success": True,
        "data": result,
    }


@router.post("/schema/validate")
async def validate_graph_schema_stateless(
    payload: SchemaImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Validate a graph schema provided in the request body (stateless).

    Useful for validating the current state of the graph builder before saving.
    Returns the same diagnostic format as the GET endpoint.
    """
    service = SchemaService(db)
    result = await service.validate_schema_data(payload.schema_data)
    return {
        "success": True,
        "data": result,
    }


@router.post("/schema/import")
async def import_graph_schema(
    payload: SchemaImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Import a ``GraphSchema`` JSON to create a new graph.

    This creates a new graph in the database with the nodes and edges
    defined in the schema. Returns the ID of the newly created graph.
    """
    service = SchemaService(db)
    graph_id = await service.import_schema(
        schema_data=payload.schema_data,
        user_id=current_user.id,
        workspace_id=payload.workspace_id,
    )
    await db.commit()

    logger.info(f"[GraphSchemaAPI] Import complete | graph_id={graph_id} | user={current_user.id}")
    return {
        "success": True,
        "data": {
            "graphId": str(graph_id),
        },
    }
