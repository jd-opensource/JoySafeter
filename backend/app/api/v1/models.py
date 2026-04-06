"""
Model management API (global, workspace-independent)
"""

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.dependencies import get_current_user
from app.common.response import success_response
from app.core.database import get_db
from app.core.model import ModelType
from app.models.auth import AuthUser as User
from app.services.model_service import ModelService

router = APIRouter(prefix="/v1/models", tags=["Models"])


class ModelInstanceCreate(BaseModel):
    """Create model instance configuration request."""

    provider_name: str = Field(description="Provider name", examples=["openaiapicompatible"])
    model_name: str = Field(description="Model name", examples=["gpt-4o"])
    model_type: str = Field(default="chat", description="Model type: chat, llm, embedding, etc.", examples=["chat"])
    model_parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="Model parameter configuration", examples=[{}]
    )


class ModelInstanceUpdate(BaseModel):
    """Update model instance request."""

    model_parameters: Optional[Dict[str, Any]] = Field(
        default=None, description="Model parameter overrides (only user-specified fields)"
    )


class ModelTestRequest(BaseModel):
    """Test model output request."""

    model_name: str = Field(description="Model name", examples=["gpt-4o"])
    input: str = Field(description="Input text", examples=["Hello, please introduce yourself"])


@router.get("/overview")
async def get_models_overview(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get global model overview: provider health summary, recent credential failures."""
    service = ModelService(db)
    overview = await service.get_overview()
    return success_response(data=overview, message="Model overview retrieved")


@router.get("")
async def list_available_models(
    model_type: str = Query(default="chat", description="Model type: chat, llm, embedding, etc."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List available models (includes unavailable_reason)."""
    try:
        model_type_enum = ModelType(model_type)
    except ValueError:
        from app.common.exceptions import BadRequestException

        raise BadRequestException(f"Unsupported model type: {model_type}")

    service = ModelService(db)
    models = await service.get_available_models(model_type=model_type_enum, user_id=current_user.id)
    return success_response(data=models, message="Model list retrieved")


@router.post("/instances")
async def create_model_instance(
    payload: ModelInstanceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a model instance configuration."""
    try:
        model_type_enum = ModelType(payload.model_type)
    except ValueError:
        from app.common.exceptions import BadRequestException

        raise BadRequestException(f"Unsupported model type: {payload.model_type}")

    service = ModelService(db)
    instance = await service.create_model_instance_config(
        user_id=current_user.id,
        provider_name=payload.provider_name,
        model_name=payload.model_name,
        model_type=model_type_enum,
        model_parameters=payload.model_parameters,
    )
    return success_response(data=instance, message="Model instance configuration created")


@router.get("/instances")
async def list_model_instances(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List model instance configurations (global)."""
    service = ModelService(db)
    instances = await service.list_model_instances()
    return success_response(data=instances, message="Model instance configurations retrieved")


@router.patch("/instances/{instance_id}")
async def update_model_instance(
    instance_id: uuid.UUID,
    payload: ModelInstanceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update model instance parameters."""
    service = ModelService(db)
    instance = await service.update_model_instance(
        instance_id=instance_id,
        model_parameters=payload.model_parameters,
    )
    return success_response(data=instance, message="Model instance updated")


class ModelTestStreamRequest(BaseModel):
    """Streaming model output test request."""

    model_name: str = Field(description="Model name")
    input: str = Field(description="Input text")
    model_parameters: Optional[Dict[str, Any]] = Field(default=None, description="Temporary parameter overrides")


@router.post("/test-output-stream")
async def test_output_stream(
    payload: ModelTestStreamRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test model output via SSE streaming."""
    service = ModelService(db)

    async def event_generator():
        async for event in service.test_output_stream(
            user_id=current_user.id,
            model_name=payload.model_name,
            input_text=payload.input,
            model_parameters=payload.model_parameters,
        ):
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/test-output")
async def test_output(
    payload: ModelTestRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Test model output."""
    service = ModelService(db)
    output = await service.test_output(
        user_id=current_user.id,
        model_name=payload.model_name,
        input_text=payload.input,
    )
    return success_response(data={"output": output}, message="Model output test completed")
