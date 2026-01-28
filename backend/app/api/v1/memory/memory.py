import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.routing import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SortOrder,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from app.api.v1.memory.schemas import (
    DeleteMemoriesRequest,
    OptimizeMemoriesRequest,
    OptimizeMemoriesResponse,
    UserMemoryCreateSchema,
    UserMemorySchema,
)
from app.common.dependencies import get_current_user
from app.core.database import get_db
from app.models.auth import AuthUser as User
from app.schemas.memory import UserMemory
from app.services.memory_service import MemoryService

logger = logging.getLogger(__name__)


# Create router and attach routes using MemoryService (async)
router = APIRouter(
    dependencies=[Depends(get_current_user)],
    tags=["User_Memory"],
    responses={
        400: {"description": "Bad Request", "model": BadRequestResponse},
        401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
        404: {"description": "Not Found", "model": NotFoundResponse},
        422: {"description": "Validation Error", "model": ValidationErrorResponse},
        500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
    },
)


def _normalize_memory_dict(mem: Dict[str, Any]) -> Dict[str, Any]:
    """Convert raw DB dict to API-friendly dict for UserMemorySchema.from_dict."""
    norm = dict(mem)
    # Ensure updated_at is datetime
    updated_at = norm.get("updated_at")
    if isinstance(updated_at, (int, float)) and updated_at is not None:
        norm["updated_at"] = datetime.fromtimestamp(updated_at, tz=timezone.utc)
    elif isinstance(updated_at, str) and updated_at:
        try:
            norm["updated_at"] = datetime.fromisoformat(updated_at)
        except Exception:
            # Fallback: leave as-is; pydantic may try to coerce
            pass
    # Ensure user_id is string to satisfy schema
    if "user_id" in norm and norm["user_id"] is not None:
        norm["user_id"] = str(norm["user_id"])
    return norm


def parse_topics(
    topics: Optional[str] = Query(
        default=None,
        description="Comma-separated list of topics to filter by",
        examples=["preferences,technical,communication_style"],
    ),
) -> Optional[List[str]]:
    """Parse comma-separated topics into a list for filtering memories by topic."""
    if not topics:
        return None

    try:
        # Split by comma and strip whitespace, filter out empty strings
        return [topic.strip() for topic in topics.split(",") if topic.strip()]

    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid topics format: {e}")


@router.post(
    "/memories",
    response_model=UserMemorySchema,
    status_code=200,
    operation_id="create_memory",
    summary="Create Memory",
    description=(
        "Create a new user memory with content and associated topics. "
        "Memories are used to store contextual information for users across conversations."
    ),
    responses={
        200: {
            "description": "Memory created successfully",
            "content": {
                "application/json": {
                    "example": {
                        "memory_id": "mem-123",
                        "memory": "User prefers technical explanations with code examples",
                        "topics": ["preferences", "communication_style", "technical"],
                        "user_id": "user-456",
                        "created_at": "2024-01-15T10:30:00Z",
                        "updated_at": "2024-01-15T10:30:00Z",
                    }
                }
            },
        },
        400: {"description": "Invalid request data", "model": BadRequestResponse},
        422: {"description": "Validation error in payload", "model": ValidationErrorResponse},
        500: {"description": "Failed to create memory", "model": InternalServerErrorResponse},
    },
)
async def create_memory(
    request: Request,
    payload: UserMemoryCreateSchema,
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserMemorySchema:
    payload.user_id = str(current_user.id)

    db = MemoryService(db_session)

    user_memory = await db.upsert_user_memory(
        memory=UserMemory(
            memory_id=str(uuid4()),
            memory=payload.memory,
            topics=payload.topics or [],
            user_id=payload.user_id,
        ),
        deserialize=False,
    )

    if not user_memory:
        raise HTTPException(status_code=500, detail="Failed to create memory")

    return UserMemorySchema.from_dict(_normalize_memory_dict(user_memory))  # type: ignore


@router.delete(
    "/memories/{memory_id}",
    status_code=204,
    operation_id="delete_memory",
    summary="Delete Memory",
    description="Permanently delete a specific user memory. This action cannot be undone.",
    responses={
        204: {"description": "Memory deleted successfully"},
        404: {"description": "Memory not found", "model": NotFoundResponse},
        500: {"description": "Failed to delete memory", "model": InternalServerErrorResponse},
    },
)
async def delete_memory(
    request: Request,
    memory_id: str = Path(description="Memory ID to delete"),
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    db = MemoryService(db_session)
    success = await db.delete_user_memory(memory_id=memory_id, user_id=str(current_user.id))
    if not success:
        raise HTTPException(status_code=404, detail=f"Memory with ID {memory_id} not found")
    return None


@router.delete(
    "/memories",
    status_code=204,
    operation_id="delete_memories",
    summary="Delete Multiple Memories",
    description=(
        "Delete multiple user memories by their IDs in a single operation. "
        "This action cannot be undone and all specified memories will be permanently removed."
    ),
    responses={
        204: {"description": "Memories deleted successfully"},
        400: {"description": "Invalid request - empty memory_ids list", "model": BadRequestResponse},
        500: {"description": "Failed to delete memories", "model": InternalServerErrorResponse},
    },
)
async def delete_memories(
    request: DeleteMemoriesRequest,
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if not request.memory_ids:
        raise HTTPException(status_code=400, detail="memory_ids must not be empty")
    db = MemoryService(db_session)
    await db.delete_user_memories(memory_ids=request.memory_ids, user_id=str(current_user.id))
    return None


@router.get(
    "/memories",
    response_model=PaginatedResponse[UserMemorySchema],
    status_code=200,
    operation_id="get_memories",
    summary="List Memories",
    description=(
        "Retrieve paginated list of user memories with filtering and search capabilities. "
        "Filter by user, agent, team, topics, or search within memory content."
    ),
)
async def get_memories(
    request: Request,
    user_id: Optional[str] = Query(default=None, description="Filter memories by user ID"),
    agent_id: Optional[str] = Query(default=None, description="Filter memories by agent ID"),
    team_id: Optional[str] = Query(default=None, description="Filter memories by team ID"),
    topics: Optional[List[str]] = Depends(parse_topics),
    search_content: Optional[str] = Query(default=None, description="Fuzzy search within memory content"),
    limit: Optional[int] = Query(default=20, description="Number of memories to return per page"),
    page: Optional[int] = Query(default=1, description="Page number for pagination"),
    sort_by: Optional[str] = Query(default="updated_at", description="Field to sort memories by"),
    sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PaginatedResponse[UserMemorySchema]:
    db = MemoryService(db_session)

    # 强制限定为当前用户
    user_id = str(current_user.id)

    # Ensure limit/page are proper ints
    limit = int(limit) if limit is not None else 20
    page = int(page) if page is not None else 1

    user_memories_raw, total_count = await db.get_user_memories(
        limit=limit,
        page=page,
        user_id=user_id,
        agent_id=agent_id,
        team_id=team_id,
        topics=topics,
        search_content=search_content,
        sort_by=sort_by,
        sort_order=sort_order,
        deserialize=False,
    )

    memories = [
        UserMemorySchema.from_dict(_normalize_memory_dict(user_memory))  # type: ignore
        for user_memory in user_memories_raw  # type: ignore
    ]
    memories = [m for m in memories if m is not None]

    return PaginatedResponse(
        data=memories,  # type: ignore
        meta=PaginationInfo(
            page=page,
            limit=limit,
            total_count=total_count,  # type: ignore
            total_pages=(total_count + limit - 1) // limit if limit is not None and limit > 0 else 0,  # type: ignore
        ),
    )


@router.get(
    "/memories/{memory_id}",
    response_model=UserMemorySchema,
    status_code=200,
    operation_id="get_memory",
    summary="Get Memory by ID",
    description="Retrieve detailed information about a specific user memory by its ID.",
    responses={
        200: {"description": "Memory retrieved successfully"},
        404: {"description": "Memory not found", "model": NotFoundResponse},
    },
)
async def get_memory(
    request: Request,
    memory_id: str = Path(description="Memory ID to retrieve"),
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserMemorySchema:
    db = MemoryService(db_session)

    user_memory = await db.get_user_memory(memory_id=memory_id, user_id=str(current_user.id), deserialize=False)
    if not user_memory:
        raise HTTPException(status_code=404, detail=f"Memory with ID {memory_id} not found")

    return UserMemorySchema.from_dict(_normalize_memory_dict(user_memory))  # type: ignore


@router.get(
    "/memory_topics",
    response_model=List[str],
    status_code=200,
    operation_id="get_memory_topics",
    summary="Get Memory Topics",
    description=(
        "Retrieve all unique topics associated with memories in the system. "
        "Useful for filtering and categorizing memories by topic."
    ),
)
async def get_topics(
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> List[str]:
    db = MemoryService(db_session)
    # 仅返回当前用户的主题；如果需要全局统计，可引入 admin 判定
    user_id = str(current_user.id)
    return await db.get_all_memory_topics(user_id=user_id)


@router.patch(
    "/memories/{memory_id}",
    response_model=UserMemorySchema,
    status_code=200,
    operation_id="update_memory",
    summary="Update Memory",
    description=(
        "Update an existing user memory's content and topics. "
        "Replaces the entire memory content and topic list with the provided values."
    ),
    responses={
        200: {"description": "Memory updated successfully"},
        400: {"description": "Invalid request data", "model": BadRequestResponse},
        404: {"description": "Memory not found", "model": NotFoundResponse},
        422: {"description": "Validation error in payload", "model": ValidationErrorResponse},
        500: {"description": "Failed to update memory", "model": InternalServerErrorResponse},
    },
)
async def update_memory(
    request: Request,
    payload: UserMemoryCreateSchema,
    memory_id: str = Path(description="Memory ID to update"),
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UserMemorySchema:
    # 强制使用当前用户
    payload.user_id = str(current_user.id)

    db = MemoryService(db_session)

    user_memory = await db.upsert_user_memory(
        memory=UserMemory(
            memory_id=memory_id,
            memory=payload.memory,
            topics=payload.topics or [],
            user_id=payload.user_id,
        ),
        deserialize=False,
    )
    if not user_memory:
        raise HTTPException(status_code=500, detail="Failed to update memory")

    return UserMemorySchema.from_dict(_normalize_memory_dict(user_memory))  # type: ignore


@router.post(
    "/optimize-memories",
    response_model=OptimizeMemoriesResponse,
    status_code=200,
    operation_id="optimize_memories",
    summary="Optimize User Memories",
    description=(
        "Optimize user memories using the default summarize strategy. "
        "This operation combines all memories into a single comprehensive summary."
    ),
)
async def optimize_memories(
    request: OptimizeMemoriesRequest,
    db_session: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OptimizeMemoriesResponse:
    """Optimize user memories using the default summarize strategy."""
    from app.core.agent.memory.manager import MemoryManager
    from app.core.agent.memory.strategies.summarize import SummarizeStrategy
    from app.core.agent.memory.strategies.types import MemoryOptimizationStrategyType

    try:
        # Create memory manager with MemoryService
        db = MemoryService(db_session)
        memory_manager = MemoryManager(db=db)

        # Get current memories to count tokens before optimization
        user_id = request.user_id or str(current_user.id)
        memories_before = await memory_manager.aget_user_memories(user_id=user_id)
        if not memories_before:
            raise HTTPException(status_code=404, detail=f"No memories found for user {user_id}")

        # Count tokens before optimization
        strategy = SummarizeStrategy()
        tokens_before = strategy.count_tokens(memories_before)
        memories_before_count = len(memories_before)

        # Optimize memories with default SUMMARIZE strategy
        optimized_memories = await memory_manager.aoptimize_memories(
            user_id=user_id,
            strategy=MemoryOptimizationStrategyType.SUMMARIZE,
            apply=request.apply,
        )

        # Count tokens after optimization
        tokens_after = strategy.count_tokens(optimized_memories)
        memories_after_count = len(optimized_memories)

        # Calculate statistics (clamp to 0 when summarization increases tokens)
        tokens_saved = max(0, tokens_before - tokens_after)
        reduction_percentage = (
            max(0.0, (tokens_before - tokens_after) / tokens_before * 100.0) if tokens_before > 0 else 0.0
        )

        # Convert to schema objects
        optimized_memory_schemas = [
            UserMemorySchema(
                memory_id=mem.memory_id or "",
                memory=mem.memory or "",
                topics=mem.topics,
                agent_id=mem.agent_id,
                team_id=mem.team_id,
                user_id=mem.user_id,
                updated_at=datetime.fromtimestamp(mem.updated_at, tz=timezone.utc)
                if isinstance(mem.updated_at, (int, float))
                else mem.updated_at,  # type: ignore
            )
            for mem in optimized_memories
        ]

        return OptimizeMemoriesResponse(
            memories=optimized_memory_schemas,
            memories_before=memories_before_count,
            memories_after=memories_after_count,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            tokens_saved=tokens_saved,
            reduction_percentage=reduction_percentage,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to optimize memories for user {request.user_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to optimize memories: {str(e)}")
