"""
Module: Conversations API

Overview:
- Provides conversation create, query, update, delete (soft/hard delete)
- Provides message pagination, checkpoint retrieval, and conversation reset
- Supports conversation data export/import and full-text search
- Provides per-user conversation statistics

Routes:
- POST /conversations: Create conversation
- GET /conversations: Get conversation list (paginated)
- DELETE /conversations/all: Delete all historical conversations (soft/hard)
- GET /conversations/{thread_id}: Get conversation details
- PATCH /conversations/{thread_id}: Update conversation
- DELETE /conversations/{thread_id}: Delete conversation (soft/hard)
- POST /conversations/{thread_id}/reset: Reset conversation (clear messages and checkpoints)
- GET /conversations/{thread_id}/messages: Get conversation messages (paginated)
- GET /conversations/{thread_id}/checkpoints: Get conversation checkpoints
- GET /conversations/{thread_id}/export: Export conversation (hidden from OpenAPI)
- POST /conversations/import: Import conversation (hidden from OpenAPI)
- POST /conversations/search: Search conversations and messages
- GET /conversations/users/stats: Get current user's conversation statistics

Dependencies:
- Auth: CurrentUser
- Database: AsyncSession (Depends(get_db))
- Graph: get_compiled_graph / LangGraph checkpoints
- Utilities: utc_now, SQLAlchemy select/func, etc.

Requests/Responses:
- Pagination: PaginationParams, PageResult[T]
- Conversation/Message models: ConversationCreate/Update/Response/DetailResponse, MessageResponse
- Others: CheckpointResponse, ConversationExportResponse, ConversationImportRequest, SearchRequest/Response, UserStatsResponse
- Unified response: BaseResponse[T]

Error codes:
- 404: Conversation not found or not owned by current user
- 400: Invalid parameters or import/export failure
- 500: Internal server error
"""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from loguru import logger
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import CurrentUser
from app.common.exceptions import raise_internal_error, raise_not_found_error
from app.common.pagination import PageResult, PaginationParams, Paginator
from app.core.agent.checkpointer.checkpointer import get_checkpointer
from app.core.agent.sample_agent import get_agent
from app.core.database import get_db
from app.models import Conversation, Message
from app.schemas import (
    BaseResponse,
    CheckpointResponse,
    ConversationCreate,
    ConversationDetailResponse,
    ConversationExportResponse,
    ConversationImportRequest,
    ConversationMessageResponse,
    ConversationResponse,
    ConversationUpdate,
    SearchRequest,
    SearchResponse,
    UserStatsResponse,
)
from app.utils.datetime import utc_now

router = APIRouter(prefix="/conversations", tags=["Conversations"])


# ==================== Helper functions ====================


async def get_compiled_graph(user_id: str, db: AsyncSession) -> Any:
    """
    Get a LangGraph runnable with checkpointer enabled.

    Notes:
        - Uses a global checkpointer instance managed by app.core.agent.checkpointer.
        - Lazily initializes the checkpointer from settings if not initialized.
        - Credentials are fetched from database.
    """
    # 从数据库获取凭据
    from app.core.model import ModelType
    from app.services.model_credential_service import ModelCredentialService
    from app.services.model_service import ModelService

    model_service = ModelService(db)
    credential_service = ModelCredentialService(db)

    # 获取默认模型
    default_instance = await model_service.repo.get_default()
    if default_instance:
        provider_name = default_instance.provider.name
        model_name = default_instance.model_name
        model_type = ModelType.CHAT  # 简化处理，假设是 Chat 模型

        credentials = await credential_service.get_current_credentials(
            provider_name=provider_name,
            model_type=model_type,
            model_name=model_name,
        )
        api_key = credentials.get("api_key") if credentials else None
        base_url = credentials.get("base_url") if credentials else None
    else:
        # 如果没有默认模型，尝试获取第一个可用的有效凭据
        all_credentials = await credential_service.list_credentials()
        for cred in all_credentials:
            if cred.get("is_valid"):
                provider_name_raw = cred.get("provider_name")
                provider_name = str(provider_name_raw) if provider_name_raw is not None else ""
                # 尝试获取该 provider 的第一个模型
                provider = await model_service.provider_repo.get_by_name(provider_name)
                if provider:
                    # 获取该 provider 的第一个模型实例
                    instances = await model_service.repo.list_all()
                    provider_instances = [i for i in instances if i.provider_id == provider.id]
                    if provider_instances:
                        model_name = provider_instances[0].model_name
                        model_type = ModelType.CHAT
                        credentials = await credential_service.get_current_credentials(
                            provider_name=provider_name,
                            model_type=model_type,
                            model_name=model_name,
                        )
                        if credentials:
                            api_key = credentials.get("api_key")
                            base_url = credentials.get("base_url")
                            break

    return await get_agent(
        checkpointer=get_checkpointer(),
        api_key=api_key,
        base_url=base_url,
        user_id=user_id,
    )


async def verify_conversation_ownership(thread_id: str, user_id: str, db: AsyncSession) -> Conversation:
    """Verify conversation ownership"""
    result = await db.execute(
        select(Conversation).where(Conversation.thread_id == thread_id, Conversation.user_id == user_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise_not_found_error("Conversation")
    # At this point, conversation is guaranteed to be non-None
    assert conversation is not None
    return conversation


# ==================== Conversation management endpoints ====================


@router.post(
    "",
    response_model=BaseResponse[ConversationResponse],
    summary="Create conversation",
    description="Create a new conversation for the current user.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def create_conversation(
    conv: ConversationCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ConversationResponse]:
    """
    Create a new conversation

    Args:
        conv: Conversation creation request
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[ConversationResponse]: Conversation response
    """
    conversation = Conversation(
        thread_id=str(uuid.uuid4()),
        user_id=current_user.id,  # Use current user ID
        title=conv.title,
        meta_data=conv.metadata or {},
    )
    db.add(conversation)
    await db.commit()
    await db.refresh(conversation)

    return BaseResponse(
        success=True,
        code=201,
        msg="Conversation created successfully",
        data=ConversationResponse(
            id=conversation.id,
            thread_id=conversation.thread_id,
            user_id=conversation.user_id,
            title=conversation.title,
            metadata=conversation.meta_data or {},
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=0,
        ),
    )


@router.get(
    "",
    response_model=BaseResponse[PageResult[ConversationResponse]],
    summary="List conversations",
    description="List the current user's conversations with pagination.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def list_conversations(
    current_user: CurrentUser,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[PageResult[ConversationResponse]]:
    """
    Get the current user's conversation list

    Args:
        current_user: Current user
        page: Page number (starting from 1)
        page_size: Number of items per page
        db: Database session

    Returns:
        BaseResponse[PageResult[ConversationResponse]]: Paginated conversation list
    """
    # Create PaginationParams from query parameters
    page_query = PaginationParams(page=page, page_size=page_size)

    paginator = Paginator(db)
    page_result = await paginator.paginate(
        select(Conversation)
        .where(Conversation.user_id == current_user.id, Conversation.is_active == 1)
        .order_by(Conversation.updated_at.desc()),
        page_query,
    )
    conversations = page_result.items

    response_list = []
    for conv in conversations:
        # Get message count
        count_result = await db.execute(select(func.count(Message.id)).where(Message.thread_id == conv.thread_id))
        message_count = count_result.scalar() or 0

        response_list.append(
            ConversationResponse(
                id=conv.id,
                thread_id=conv.thread_id,
                user_id=conv.user_id,
                title=conv.title,
                metadata=conv.meta_data or {},
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=message_count,
            )
        )

    return BaseResponse(
        success=True,
        code=200,
        msg="Fetched conversation list successfully",
        data=PageResult(
            items=response_list,
            total=page_result.total,
            page=page_result.page,
            page_size=page_result.page_size,
            pages=page_result.pages,
        ),
    )


@router.delete(
    "/all",
    summary="Delete all historical conversations",
    description="Delete all conversations for the current user. Supports soft delete or hard delete.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def delete_all_conversations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    hard_delete: bool = True,
) -> BaseResponse:
    """Delete all historical conversations for the current user

    Args:
        current_user: Current authenticated user
        db: Database session
        hard_delete: Whether to hard delete (permanent), defaults to True

    Returns:
        BaseResponse: Delete result
    """
    # Get all conversations for the current user
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == current_user.id, Conversation.is_active == 1)
    )
    conversations = result.scalars().all()

    if not conversations:
        return BaseResponse(
            success=True,
            code=200,
            msg="No conversations to delete",
            data={"deleted_count": 0},
        )

    deleted_count = 0

    if hard_delete:
        # Hard delete: remove all conversations and related data
        from app.core.agent.checkpointer.checkpointer import delete_thread_checkpoints

        for conversation in conversations:
            try:
                # 删除检查点
                await delete_thread_checkpoints(conversation.thread_id)
            except Exception as e:
                logger.warning(f"Failed to delete checkpoints for {conversation.thread_id}: {e}")

            # 删除会话（消息会通过 cascade 自动删除）
            await db.delete(conversation)
            deleted_count += 1
    else:
        # Soft delete: mark all conversations as inactive
        for conversation in conversations:
            conversation.is_active = 0
            deleted_count += 1

    await db.commit()

    return BaseResponse(
        success=True,
        code=200,
        msg=f"Deleted {deleted_count} conversations successfully",
        data={
            "deleted_count": deleted_count,
            "hard_delete": hard_delete,
        },
    )


@router.get(
    "/{thread_id}",
    response_model=BaseResponse[ConversationDetailResponse],
    summary="Get conversation details",
    description="Get conversation details by thread_id for the current user.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_conversation(
    thread_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[ConversationDetailResponse]:
    """
    Get a single conversation's details

    Args:
        thread_id: Thread ID
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[ConversationDetailResponse]: Conversation details
    """
    # Verify conversation ownership
    conversation = await verify_conversation_ownership(thread_id, current_user.id, db)

    messages_result = await db.execute(
        select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at)
    )
    messages = messages_result.scalars().all()

    conv_response = ConversationResponse(
        id=conversation.id,
        thread_id=conversation.thread_id,
        user_id=conversation.user_id,
        title=conversation.title,
        metadata=conversation.meta_data or {},
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        message_count=len(messages),
    )

    messages_data = [
        {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "metadata": msg.meta_data or {},
            "created_at": msg.created_at.isoformat(),
        }
        for msg in messages
    ]

    return BaseResponse(
        success=True,
        code=200,
        msg="Fetched conversation details successfully",
        data=ConversationDetailResponse(conversation=conv_response, messages=messages_data),
    )


@router.patch(
    "/{thread_id}",
    response_model=BaseResponse[dict],
    summary="Update conversation",
    description="Update conversation title and/or metadata.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def update_conversation(
    thread_id: str,
    update: ConversationUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[dict]:
    """
    Update conversation information

    Args:
        thread_id: Thread ID
        update: Update payload
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[dict]: Update status
    """
    # Verify conversation ownership
    conversation = await verify_conversation_ownership(thread_id, current_user.id, db)

    if update.title is not None:
        conversation.title = update.title
    if update.metadata is not None:
        conversation.meta_data = update.metadata

    conversation.updated_at = utc_now()
    await db.commit()

    return BaseResponse(
        success=True,
        code=200,
        msg="Conversation updated successfully",
        data={"status": "updated", "thread_id": thread_id},
    )


@router.delete(
    "/{thread_id}",
    response_model=BaseResponse[dict],
    summary="Delete conversation",
    description="Delete a conversation (soft delete or hard delete). Hard delete removes all related data.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def delete_conversation(
    thread_id: str,
    current_user: CurrentUser,
    hard_delete: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """
    Delete conversation (soft or hard delete), hard delete by default

    Args:
        thread_id: Thread ID
        hard_delete: Whether to hard delete
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[dict]: Delete status
    """
    # Verify conversation ownership
    conversation = await verify_conversation_ownership(thread_id, current_user.id, db)

    if hard_delete:
        # Hard delete: remove all related data
        # Delete checkpoints first
        from app.core.agent.checkpointer.checkpointer import delete_thread_checkpoints

        try:
            await delete_thread_checkpoints(thread_id)
        except Exception as e:
            logger.warning(f"Failed to delete checkpoints: {e}")

        # Delete conversation (messages are cascade-deleted)
        await db.delete(conversation)
    else:
        # Soft delete
        conversation.is_active = 0

    await db.commit()
    return BaseResponse(
        success=True,
        code=200,
        msg="Conversation deleted successfully",
        data={"status": "deleted", "thread_id": thread_id},
    )


@router.post(
    "/{thread_id}/reset",
    response_model=BaseResponse[dict],
    summary="Reset conversation",
    description="Clear all checkpoints and messages, but keep the conversation record.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def reset_conversation(
    thread_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[dict]:
    """
    Reset conversation: clear all checkpoints and messages, but keep the conversation record

    After reset, the conversation returns to the initial state and can start over.

    Args:
        thread_id: Thread ID
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[dict]: Reset status
    """
    # Verify conversation ownership
    conversation = await verify_conversation_ownership(thread_id, current_user.id, db)

    try:
        # 1. Delete LangGraph checkpoints
        from app.core.agent.checkpointer.checkpointer import delete_thread_checkpoints

        await delete_thread_checkpoints(thread_id)
        logger.info(f"✅ Deleted LangGraph checkpoints for thread: {thread_id}")

        # 2. Delete all message records
        result = await db.execute(delete(Message).where(Message.thread_id == thread_id))
        # 获取删除的行数（SQLAlchemy 2.0+ 的 Result 对象有 rowcount 属性）
        deleted_count = getattr(result, "rowcount", 0)
        logger.info(f"✅ Deleted {deleted_count} messages for thread: {thread_id}")

        # 3. Update conversation timestamp
        conversation.updated_at = utc_now()

        await db.commit()

        return BaseResponse(
            success=True,
            code=200,
            msg=f"Conversation reset; deleted {deleted_count} messages",
            data={
                "status": "reset",
                "thread_id": thread_id,
                "deleted_count": deleted_count,
            },
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"❌ Failed to reset conversation {thread_id}: {e}")
        raise_internal_error(f"Failed to reset conversation: {str(e)}")
        return BaseResponse(success=False, code=500, msg=f"Failed to reset conversation: {str(e)}", data={})  # type: ignore[unreachable]


# ==================== Message management endpoints ====================


@router.get(
    "/{thread_id}/messages",
    response_model=BaseResponse[PageResult[ConversationMessageResponse]],
    summary="List conversation messages",
    description="Get a paginated list of messages in the conversation.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_messages(
    thread_id: str,
    current_user: CurrentUser,
    page_query: PaginationParams = Depends(),
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[PageResult[ConversationMessageResponse]]:
    """
    Get conversation message history

    Args:
        thread_id: Thread ID
        current_user: Current user
        page_query: Pagination parameters (page, page_size)
        db: Database session

    Returns:
        BaseResponse[PageResult[ConversationMessageResponse]]: Paginated message list
    """
    # Verify conversation ownership
    await verify_conversation_ownership(thread_id, current_user.id, db)

    paginator = Paginator(db)
    page_result = await paginator.paginate(
        select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at.desc()),
        page_query,
    )
    messages = page_result.items

    message_list = [
        ConversationMessageResponse(
            id=msg.id,
            role=msg.role,
            content=msg.content,
            metadata=msg.meta_data or {},
            created_at=msg.created_at,
        )
        for msg in reversed(list(messages))
    ]

    # Debug logging
    logger.info(f"Loaded {len(message_list)} messages for thread {thread_id}")
    for msg in message_list:
        logger.info(f"  - role={msg.role}, content_length={len(msg.content) if msg.content else 0}")

    return BaseResponse(
        success=True,
        code=200,
        msg="Fetched message list successfully",
        data=PageResult(
            items=message_list,
            total=page_result.total,
            page=page_result.page,
            page_size=page_result.page_size,
            pages=page_result.pages,
        ),
    )


@router.get(
    "/{thread_id}/checkpoints",
    response_model=BaseResponse[CheckpointResponse],
    summary="Get conversation checkpoints",
    description="Retrieve checkpoints from LangGraph state history.",
    responses={
        401: {"description": "Unauthorized"},
        404: {"description": "Conversation not found"},
        500: {"description": "Internal server error"},
    },
)
async def get_checkpoints(
    thread_id: str,
    current_user: CurrentUser,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[CheckpointResponse]:
    """
    Get all conversation checkpoints

    Args:
        thread_id: Thread ID
        limit: Number of checkpoints to return

    Returns:
        BaseResponse[CheckpointResponse]: Checkpoints response
    """
    # Verify conversation ownership
    await verify_conversation_ownership(thread_id, current_user.id, db)

    config = {"configurable": {"thread_id": thread_id, "user_id": str(current_user.id)}}
    try:
        compiled_graph = await get_compiled_graph(current_user.id, db)
        checkpoints = []
        async for checkpoint in compiled_graph.aget_state_history(config):
            checkpoints.append(
                {
                    "checkpoint_id": checkpoint.config["configurable"].get("checkpoint_id"),
                    "values": checkpoint.values,
                    "next": checkpoint.next,
                    "metadata": checkpoint.metadata,
                    "created_at": checkpoint.created_at.isoformat() if checkpoint.created_at else None,
                }
            )
            if len(checkpoints) >= limit:
                break

        return BaseResponse(
            success=True,
            code=200,
            msg="Fetched checkpoints successfully",
            data=CheckpointResponse(thread_id=thread_id, checkpoints=checkpoints),
        )
    except Exception as e:
        logger.error(f"Get checkpoints error: {e}")
        raise_internal_error(str(e))
        return BaseResponse(
            success=False, code=500, msg=str(e), data=CheckpointResponse(thread_id=thread_id, checkpoints=[])
        )  # type: ignore[unreachable]


async def get_graph_instance(
    llm_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_tokens: int = 4096,
    user_id: Any | None = None,
    db: AsyncSession | None = None,
) -> Any:
    """
    Get a LangGraph graph instance configured per user.

    Notes:
        - This function creates a new graph instance on each call.
        - All graph instances share the same checkpointer (state persistence).
        - Each user has an isolated working directory at /tmp/{user_id}.
        - If credentials are not provided, they will be fetched from database.

    Args:
        llm_model: LLM model name.
        api_key: API key (optional, will be fetched from database if not provided).
        base_url: API base URL (optional, will be fetched from database if not provided).
        max_tokens: Maximum token count.
        user_id: User ID (UUID), used to create an isolated working directory.
        db: Database session (required if credentials are not provided).

    Returns:
        CompiledGraph: The compiled graph object.
    """
    # 如果没有提供凭据，从数据库获取
    if not api_key and db:
        from app.core.model.utils.credential_resolver import LLMCredentialResolver

        fetched_api_key, fetched_base_url, fetched_model_name = await LLMCredentialResolver.get_credentials(
            db=db,
            api_key=api_key,
            base_url=base_url,
            llm_model=llm_model,
        )

        # Update values if fetched from database
        if fetched_api_key:
            api_key = fetched_api_key
        if fetched_base_url:
            base_url = fetched_base_url
        if fetched_model_name:
            llm_model = fetched_model_name

    graph = await get_agent(
        checkpointer=get_checkpointer(),
        llm_model=llm_model,
        api_key=api_key,
        base_url=base_url,
        max_tokens=max_tokens,
        user_id=user_id,
    )
    logger.debug(f"Created new graph instance with config: model={llm_model}, max_tokens={max_tokens}")
    return graph


# ==================== Export/Import endpoints ====================


@router.get("/{thread_id}/export", response_model=BaseResponse[ConversationExportResponse], include_in_schema=False)
async def export_conversation(
    thread_id: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Export conversation data

    Args:
        thread_id: Thread ID
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[ConversationExportResponse]: Exported data
    """
    # Verify conversation ownership
    conversation = await verify_conversation_ownership(thread_id, current_user.id, db)

    messages_result = await db.execute(
        select(Message).where(Message.thread_id == thread_id).order_by(Message.created_at)
    )
    messages = messages_result.scalars().all()

    # Get LangGraph state
    config = {"configurable": {"thread_id": thread_id, "user_id": str(current_user.id)}}
    try:
        compiled_graph = await get_compiled_graph(current_user.id, db)
        state = await compiled_graph.aget_state(config)
        state_values = state.values
    except Exception:
        state_values = None

    return BaseResponse(
        success=True,
        code=200,
        msg="Conversation exported successfully",
        data=ConversationExportResponse(
            conversation={
                "thread_id": conversation.thread_id,
                "user_id": conversation.user_id,
                "title": conversation.title,
                "metadata": conversation.meta_data or {},
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
            },
            messages=[
                {
                    "role": msg.role,
                    "content": msg.content,
                    "metadata": msg.meta_data or {},
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ],
            state=state_values,
        ),
    )


@router.post("/import", include_in_schema=False)
async def import_conversation(
    request: ConversationImportRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(
        get_db,
    ),
):
    """
    Import conversation data

    Args:
        request: Import request
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[dict]: Import status
    """
    data = request.data
    thread_id = str(uuid.uuid4())

    # Create conversation
    conversation = Conversation(
        thread_id=thread_id,
        user_id=current_user.id,  # 使用当前用户ID
        title=data["conversation"]["title"],
        meta_data=data["conversation"].get("metadata", {}),
    )
    db.add(conversation)

    # Import messages
    for msg_data in data["messages"]:
        message = Message(
            thread_id=thread_id,
            role=msg_data["role"],
            content=msg_data["content"],
            meta_data=msg_data.get("metadata", {}),
        )
        db.add(message)

    await db.commit()

    # Restore LangGraph state
    if "state" in data and data["state"]:
        config = {"configurable": {"thread_id": thread_id, "user_id": str(current_user.id)}}
        try:
            compiled_graph = await get_compiled_graph(current_user.id, db)
            await compiled_graph.aupdate_state(config, data["state"])
        except Exception as e:
            logger.warning(f"Could not restore state: {e}")

    return BaseResponse(
        success=True,
        code=200,
        msg="Conversation imported successfully",
        data={"thread_id": thread_id, "status": "imported"},
    )


# ==================== Search endpoints ====================


@router.post(
    "/search",
    response_model=BaseResponse[SearchResponse],
    summary="Search conversations and messages",
    description="Search messages content and related conversation titles for the current user.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def search_conversations(
    request: SearchRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[SearchResponse]:
    """
    Search conversations and messages

    Args:
        request: Search request
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[SearchResponse]: Search results
    """
    # Use SQLite LIKE search
    result = await db.execute(
        select(Message)
        .join(Conversation, Message.thread_id == Conversation.thread_id)
        .where(Message.content.like(f"%{request.query}%"), Conversation.user_id == current_user.id)
        .order_by(Message.created_at.desc())
        .offset(request.skip)
        .limit(request.limit)
    )
    messages = result.scalars().all()

    results = []
    for msg in messages:
        conv_result = await db.execute(select(Conversation).where(Conversation.thread_id == msg.thread_id))
        conversation = conv_result.scalar_one_or_none()

        results.append(
            {
                "message_id": msg.id,
                "thread_id": msg.thread_id,
                "conversation_title": conversation.title if conversation else "",
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat(),
            }
        )

    return BaseResponse(
        success=True,
        code=200,
        msg="Search completed",
        data=SearchResponse(query=request.query, results=results),
    )


# ==================== Statistics endpoints ====================


@router.get(
    "/users/stats",
    response_model=BaseResponse[UserStatsResponse],
    summary="Get user statistics",
    description="Get statistics about the current user's conversations and messages.",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def get_user_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BaseResponse[UserStatsResponse]:
    """
    Get user statistics

    Args:
        current_user: Current user
        db: Database session

    Returns:
        BaseResponse[UserStatsResponse]: User statistics
    """
    # 总会话数
    conv_result = await db.execute(
        select(func.count(Conversation.id)).where(Conversation.user_id == current_user.id, Conversation.is_active == 1)
    )
    total_conversations = conv_result.scalar() or 0

    # 总消息数
    msg_result = await db.execute(
        select(func.count(Message.id))
        .join(Conversation, Message.thread_id == Conversation.thread_id)
        .where(Conversation.user_id == current_user.id)
    )
    total_messages = msg_result.scalar() or 0

    # 最近会话
    recent_result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id, Conversation.is_active == 1)
        .order_by(Conversation.updated_at.desc())
        .limit(5)
    )
    recent_conversations = recent_result.scalars().all()

    return BaseResponse(
        success=True,
        code=200,
        msg="Fetched statistics successfully",
        data=UserStatsResponse(
            user_id=str(current_user.id),
            total_conversations=total_conversations,
            total_messages=total_messages,
            recent_conversations=[
                {"thread_id": conv.thread_id, "title": conv.title, "updated_at": conv.updated_at.isoformat()}
                for conv in recent_conversations
            ],
        ),
    )
