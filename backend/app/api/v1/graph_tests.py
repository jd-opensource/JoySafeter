"""
Graph Tests API — endpoints for managing and executing graph test cases.
"""

from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.exceptions import NotFoundException
from app.core.database import get_db
from app.models.auth import AuthUser
from app.models.workspace import WorkspaceMemberRole
from app.services.graph_service import GraphService
from app.services.test_service import TestService

graph_test_router = APIRouter(prefix="/v1/graphs", tags=["graph_tests"])
test_router = APIRouter(prefix="/v1/tests", tags=["graph_tests"])


async def _get_graph_and_verify_access(
    graph_id: UUID,
    db: AsyncSession,
    current_user: AuthUser,
    required_role: WorkspaceMemberRole = WorkspaceMemberRole.member,
):
    """Fetch graph by ID and verify user access, raising on failure."""
    graph_service = GraphService(db)
    graph = await graph_service.graph_repo.get(graph_id)
    if not graph:
        raise NotFoundException("Graph not found")
    await graph_service._ensure_access(graph, current_user, required_role)
    return graph


@graph_test_router.post("/{graph_id}/tests", response_model=Dict[str, Any])
async def create_test_case(
    graph_id: UUID,
    data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """Create a new test case."""
    await _get_graph_and_verify_access(graph_id, db, current_user)
    service = TestService(db)
    try:
        test_case = await service.create_test_case(graph_id, data)
        return {
            "id": str(test_case.id),
            "name": test_case.name,
            "description": test_case.description,
            "inputs": test_case.inputs,
            "expected_outputs": test_case.expected_outputs,
            "assertions": test_case.assertions,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@graph_test_router.get("/{graph_id}/tests", response_model=List[Dict[str, Any]])
async def get_test_cases(
    graph_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """Get all test cases for a graph."""
    await _get_graph_and_verify_access(graph_id, db, current_user, WorkspaceMemberRole.viewer)
    service = TestService(db)
    test_cases = await service.get_test_cases(graph_id)
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "description": t.description,
            "inputs": t.inputs,
            "expected_outputs": t.expected_outputs,
            "assertions": t.assertions,
        }
        for t in test_cases
    ]


@test_router.patch("/{test_id}", response_model=Dict[str, Any])
async def update_test_case(
    test_id: UUID,
    data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """Update a test case."""
    service = TestService(db)
    test_case = await service.get_test_case(test_id)
    if not test_case:
        raise NotFoundException("Test case not found")
    await _get_graph_and_verify_access(test_case.graph_id, db, current_user)

    test_case = await service.update_test_case(test_id, data)
    return {
        "id": str(test_case.id),
        "name": test_case.name,
        "description": test_case.description,
        "inputs": test_case.inputs,
        "expected_outputs": test_case.expected_outputs,
        "assertions": test_case.assertions,
    }


@test_router.delete("/{test_id}", status_code=204)
async def delete_test_case(
    test_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """Delete a test case."""
    service = TestService(db)
    test_case = await service.get_test_case(test_id)
    if not test_case:
        raise NotFoundException("Test case not found")
    await _get_graph_and_verify_access(test_case.graph_id, db, current_user)

    await service.delete_test_case(test_id)


@graph_test_router.post("/{graph_id}/tests/run", response_model=Dict[str, Any])
async def run_test_suite(
    graph_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AuthUser = Depends(get_current_user),
):
    """Run all test cases for a graph."""
    await _get_graph_and_verify_access(graph_id, db, current_user)
    service = TestService(db)
    try:
        return await service.run_test_suite(graph_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
