"""
Graph Tests API
"""

from typing import Any, Dict, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_db
from app.services.test_service import TestService

router = APIRouter()


@router.post("/graphs/{graph_id}/tests", response_model=Dict[str, Any])
async def create_test_case(
    graph_id: UUID,
    data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Create a new test case."""
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


@router.get("/graphs/{graph_id}/tests", response_model=List[Dict[str, Any]])
async def get_test_cases(
    graph_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get all test cases for a graph."""
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


@router.patch("/tests/{test_id}", response_model=Dict[str, Any])
async def update_test_case(
    test_id: UUID,
    data: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
):
    """Update a test case."""
    service = TestService(db)
    test_case = await service.update_test_case(test_id, data)
    if not test_case:
        raise HTTPException(status_code=404, detail="Test case not found")

    return {
        "id": str(test_case.id),
        "name": test_case.name,
        "description": test_case.description,
        "inputs": test_case.inputs,
        "expected_outputs": test_case.expected_outputs,
        "assertions": test_case.assertions,
    }


@router.delete("/tests/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_test_case(
    test_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a test case."""
    service = TestService(db)
    success = await service.delete_test_case(test_id)
    if not success:
        raise HTTPException(status_code=404, detail="Test case not found")


@router.post("/graphs/{graph_id}/tests/run", response_model=Dict[str, Any])
async def run_test_suite(
    graph_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Run all test cases for a graph."""
    service = TestService(db)
    try:
        return await service.run_test_suite(graph_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
